"""End-to-end standard-code pipeline: ingest -> parse -> Gemini fallback -> JSON.

Flow (see docs/PIPELINE.md):
  1. Ingestion (``src/ingestion/standard_code_extractor.py``) finds
     candidate codes in PDF (pdfplumber), DOCX (python-docx) and Excel
     (pandas). Scanned PDFs without extractable text are skipped: OCR
     is out of scope.
  2. Deterministic parsing (``src/parsers/std_code_parser.py``) scores
     org 0.2 + main 0.3 + year 0.3 + parts 0.1 + suffix 0.1.
     ``confidence_score >= 0.8`` => ``verified=True``, no AI call.
  3. Otherwise (score < 0.8 or parse failure), the Gemini fallback in
     ``src/ai/gemini_standard_normalizer.py`` is called by default:
     ``suggest_standard_code(raw_text)`` is invoked directly, not
     simulated. Its result always stays ``verified=False`` and
     carries an ``explanation``. Pass ``use_ai_fallback=False``
     (CLI: ``--no-ai-fallback``) only to run fully offline.
  4. Output is a JSON array with exactly the fields in the spec:
     raw_text, corrected_code, organization, main_number, year, parts,
     suffix, confidence_score, verified, explanation.

Run from the repo root, e.g.:
    PYTHONPATH=src python -m pipeline sample.docx
    PYTHONPATH=src python -m pipeline sample.pdf -o out.json
    PYTHONPATH=src python -m pipeline sample.pdf --no-ai-fallback -o out.json

``ai_suggester`` is an injectable callable ``(raw_text) -> dict`` used
by the tests. In production it defaults to Gemini's
``suggest_standard_code`` and therefore needs GEMINI_API_KEY (see
.env.example). If Gemini is unavailable, the pipeline does *not*
crash: it returns the deterministic result, verified=False, with a
clear configuration/request error recorded in ``explanation``.
"""

import argparse
import json
import re
import sys
from decimal import Decimal
from pathlib import Path

try:
    from src.ingestion.standard_code_extractor import (
        STANDARD_CODE_PATTERN,
        extract_standard_codes,
    )
    from src.parsers.std_code_parser import parse_standard_code
except ModuleNotFoundError:  # running with src/ itself on PYTHONPATH
    from ingestion.standard_code_extractor import (  # type: ignore
        STANDARD_CODE_PATTERN,
        extract_standard_codes,
    )
    from parsers.std_code_parser import parse_standard_code  # type: ignore

# Real Gemini integration, imported at module level (not simulated).
# This is the function process_candidate calls for every score < 0.8
# when the fallback is enabled (the default). If the Gemini module
# cannot be imported at all (e.g. python-dotenv missing), the names
# below fall back to placeholder exception classes and
# _default_ai_suggester raises a clear configuration error instead
# of crashing on import, so deterministic-only runs still work.
try:
    from src.ai.gemini_standard_normalizer import (
        GeminiConfigurationError,
        GeminiRequestError,
        suggest_standard_code,
    )
    _GEMINI_IMPORT_ERROR = None
except ImportError as _gemini_import_exc:
    try:
        from ai.gemini_standard_normalizer import (  # type: ignore
            GeminiConfigurationError,
            GeminiRequestError,
            suggest_standard_code,
        )
        _GEMINI_IMPORT_ERROR = None
    except ImportError as _gemini_import_exc2:
        suggest_standard_code = None  # type: ignore

        class GeminiConfigurationError(RuntimeError):  # type: ignore
            """Placeholder when the real Gemini module is unavailable."""

        class GeminiRequestError(RuntimeError):  # type: ignore
            """Placeholder when the real Gemini module is unavailable."""

        _GEMINI_IMPORT_ERROR = _gemini_import_exc2


OUTPUT_FIELDS = (
    "raw_text",
    "corrected_code",
    "organization",
    "main_number",
    "year",
    "parts",
    "suffix",
    "confidence_score",
    "verified",
    "explanation",
)


def _float_score(value) -> float:
    if isinstance(value, Decimal):
        return round(float(value), 3)
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return 0.0


def build_canonical_code(parsed: dict) -> str | None:
    """Rebuild ``ORG MAIN[-PARTS]:YEAR[/SUFFIX]`` from a parsed result."""
    main = parsed.get("std_main_number")
    if not main:
        return None
    org = parsed.get("org_normalized") or parsed.get("org_prefix")
    parts = parsed.get("std_parts") or []
    code = f"{main}-{ '-'.join(parts)}" if parts else str(main)
    if parsed.get("series_letter"):
        code = f"{parsed['series_letter']} {code}"
    if org:
        code = f"{org} {code}"
    year = parsed.get("std_year")
    if year is not None:
        code = f"{code}:{year}"
    suffix = parsed.get("suffix")
    if suffix:
        # Suffixes that already carry their own separator (+A1, -02)
        # must not get an extra "/".
        if suffix.startswith(("-", "+")):
            code = f"{code}{suffix}"
        else:
            code = f"{code}/{suffix}"
    return code


def _default_ai_suggester(raw_text: str) -> dict:
    """Call Gemini's real ``suggest_standard_code`` for ``raw_text``."""
    if suggest_standard_code is None:
        raise GeminiConfigurationError(
            "Gemini module could not be imported "
            f"({_GEMINI_IMPORT_ERROR}); install the pipeline dependencies "
            "(see requirements.txt) and set GEMINI_API_KEY to enable "
            "the Gemini fallback."
        )
    return suggest_standard_code(raw_text)


def _record_from_parsed(raw_text: str, parsed: dict, *, verified: bool,
                        explanation: str, corrected_code=None) -> dict:
    parts_list = parsed.get("std_parts") or []
    parts = "-".join(parts_list) if parts_list else None
    # std_part keeps the leading-dash form ("-1-2"); prefer the clean join.
    if parts is None and parsed.get("std_part"):
        parts = str(parsed["std_part"]).strip("-") or None
    if corrected_code is None:
        corrected_code = build_canonical_code(parsed) or parsed.get("normalized_code") or raw_text
    return {
        "raw_text": raw_text,
        "corrected_code": corrected_code,
        "organization": parsed.get("org_normalized") or parsed.get("org_prefix"),
        "main_number": parsed.get("std_main_number"),
        "year": parsed.get("std_year"),
        "parts": parts,
        "suffix": parsed.get("suffix"),
        "confidence_score": _float_score(parsed.get("confidence_score", 0.0)),
        "verified": bool(verified),
        "explanation": explanation or "",
    }


def process_candidate(raw_text: str, *, use_ai_fallback: bool = True,
                      ai_suggester=None) -> dict:
    """Process one candidate string through parse -> (optional) Gemini -> JSON."""
    raw_text = (raw_text or "").strip()
    parsed = parse_standard_code(raw_text)

    if parsed.get("verified"):
        return _record_from_parsed(
            raw_text, parsed, verified=True,
            explanation="Deterministic parse passed (confidence >= 0.8); no AI correction applied.",
        )

    if not use_ai_fallback:
        missing = []
        if parsed.get("std_year") is None:
            missing.append("year missing in source")
        if parsed.get("std_main_number") is None:
            missing.append("could not parse main number")
        detail = f" ({'; '.join(missing)})" if missing else ""
        return _record_from_parsed(
            raw_text, parsed, verified=False,
            explanation=f"Deterministic parse below threshold (confidence < 0.8); AI fallback not enabled{detail}.",
        )

    # Score < 0.8 or parse failure: Gemini research / correction.
    # This is a real call to suggest_standard_code(raw_text), not a
    # simulated message. The two Gemini error types are handled
    # separately so a missing key and a network/API failure are
    # reported differently, and neither crashes the run.
    suggester = ai_suggester or _default_ai_suggester
    try:
        suggestion = suggester(raw_text) or {}
    except GeminiConfigurationError as exc:
        return _record_from_parsed(
            raw_text, parsed, verified=False,
            explanation=(
                f"AI fallback unavailable: {exc}. Set GEMINI_API_KEY in "
                ".env (see .env.example) to enable Gemini correction; "
                "kept deterministic result."
            ),
        )
    except GeminiRequestError as exc:
        return _record_from_parsed(
            raw_text, parsed, verified=False,
            explanation=(
                f"AI fallback failed (Gemini request error: {exc}); "
                "kept deterministic result."
            ),
        )
    except Exception as exc:  # never let one bad candidate kill the run
        return _record_from_parsed(
            raw_text, parsed, verified=False,
            explanation=f"AI fallback failed ({exc}); kept deterministic result.",
        )

    explanation = suggestion.get("explanation") or suggestion.get("reason", "")
    candidate = (suggestion.get("suggested_code") or "").strip()
    if candidate:
        candidate_parsed = parse_standard_code(candidate)
        if candidate_parsed.get("std_main_number") is not None:
            # AI-corrected code: keep the AI confidence in the record only
            # as context in the explanation if it differs; the score itself
            # stays the deterministic score of the corrected code so the
            # number is always reproducible from the parser.
            return _record_from_parsed(
                raw_text, candidate_parsed, verified=False,
                explanation=explanation or f"AI suggested correction (status: {suggestion.get('status')}).",
                corrected_code=build_canonical_code(candidate_parsed) or candidate,
            )
        return _record_from_parsed(
            raw_text, parsed, verified=False,
            explanation=explanation or "AI suggested a code that could not be re-parsed; kept original.",
            corrected_code=candidate,
        )

    return _record_from_parsed(
        raw_text, parsed, verified=False,
        explanation=explanation or f"AI could not correct this code (status: {suggestion.get('status')}).",
    )


def process_text(text: str, *, use_ai_fallback: bool = True, ai_suggester=None) -> list[dict]:
    """Extract candidates from a plain-text string and process each one."""
    seen = set()
    records = []
    for match in STANDARD_CODE_PATTERN.finditer(text or ""):
        raw = re.sub(r"\s+", " ", match.group("code")).strip(" .;,|\t\r\n")
        if not raw:
            continue
        key = re.sub(r"\s+", " ", raw).strip().upper()
        if key in seen:
            continue
        seen.add(key)
        records.append(process_candidate(
            raw, use_ai_fallback=use_ai_fallback, ai_suggester=ai_suggester))
    return records


def process_document(file_path, *, use_ai_fallback: bool = True, ai_suggester=None) -> list[dict]:
    """Run the full pipeline over one PDF / DOCX / Excel file.

    Ingestion itself is always deterministic (``use_ai_fallback=False``
    there) so Gemini, when enabled, is called exactly once per
    unverified candidate in this stage -- not once per raw occurrence.
    """
    candidates = extract_standard_codes(file_path, use_ai_fallback=False)
    records = []
    for item in candidates:
        raw = item.get("code") or item.get("raw_text") or ""
        parsed = item.get("parsed")
        if parsed is not None and parsed.get("verified"):
            records.append(_record_from_parsed(
                raw, parsed, verified=True,
                explanation="Deterministic parse passed (confidence >= 0.8); no AI correction applied.",
            ))
        else:
            # Reuse process_candidate for the threshold + Gemini logic.
            records.append(process_candidate(
                raw, use_ai_fallback=use_ai_fallback, ai_suggester=ai_suggester))
    return records


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Standard-code extraction pipeline")
    parser.add_argument("files", nargs="*", help="PDF / DOCX / Excel files to process")
    parser.add_argument("--text", help="Process a raw text string instead of files")
    parser.add_argument("--use-ai-fallback", action="store_true", default=None,
                        help="Call Gemini for codes with confidence < 0.8 (needs GEMINI_API_KEY). "
                             "This is now the default; the flag is kept for compatibility.")
    parser.add_argument("--no-ai-fallback", action="store_true",
                        help="Do NOT call Gemini for codes with confidence < 0.8; "
                             "return the deterministic result instead (fully offline).")
    parser.add_argument("-o", "--output", help="Write JSON to this file instead of stdout")
    args = parser.parse_args(argv)

    # Default is Gemini ON. --no-ai-fallback wins over --use-ai-fallback.
    use_ai_fallback = True
    if args.no_ai_fallback:
        use_ai_fallback = False
    elif args.use_ai_fallback is not None:
        use_ai_fallback = args.use_ai_fallback

    records: list[dict] = []
    if args.text:
        records = process_text(args.text, use_ai_fallback=use_ai_fallback)
    elif args.files:
        for file_path in args.files:
            records.extend(process_document(file_path, use_ai_fallback=use_ai_fallback))
    else:
        parser.error("Provide at least one file or --text")

    payload = json.dumps(records, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
