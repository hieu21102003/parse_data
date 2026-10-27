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
  4. Output is a JSON array with fields:
     raw_text, corrected_code, standard_name, organization, main_number, year, parts,
     suffix, confidence_score, verified, explanation.

Run from the repo root, e.g.:
    PYTHONPATH=src python -m pipeline sample.docx
    PYTHONPATH=src python -m pipeline sample.pdf -o out.json
    PYTHONPATH=src python -m pipeline sample.pdf --no-ai-fallback -o out.json
    PYTHONPATH=src python -m pipeline --text "TCVN 1234:2020" -o ket_qua.xlsx
      # -> formatted Excel file with exactly 7 columns (see
      # src/exporter/excel_exporter.py) and a confirmation message.

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
        STANDARD_CODE_BASE_PATTERN,
        STANDARD_CODE_PATTERN,
        clean_code_candidate,
        extract_first_clean_code,
        extract_standard_codes,
        standard_name_for_parts,
    )
    from src.parsers.std_code_parser import parse_standard_code
except ModuleNotFoundError:  # running with src/ itself on PYTHONPATH
    from ingestion.standard_code_extractor import (  # type: ignore
        STANDARD_CODE_BASE_PATTERN,
        STANDARD_CODE_PATTERN,
        clean_code_candidate,
        extract_first_clean_code,
        extract_standard_codes,
        standard_name_for_parts,
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
    "standard_name",
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


def build_canonical_code(parsed: dict, org=None) -> str | None:
    """Rebuild ``ORG MAIN[-PARTS]:YEAR[/SUFFIX]`` from a parsed result.

    ``org`` overrides the organization used in the rebuilt code
    (default: the normalized org). It exists so an expanded
    record's ``raw_text`` can keep the org exactly as written in
    the source (e.g. ``BS EN``) while ``corrected_code`` uses the
    normalized org (``EN``).
    """
    main = parsed.get("std_main_number")
    if not main:
        return None
    org = org or parsed.get("org_normalized") or parsed.get("org_prefix")
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
    # Guarantee point for raw_text: the output record's raw_text is
    # always exactly one cleaned matched code, never a row, paragraph
    # or cell string that happened to contain a code. If the input
    # contains a standard-code match, it is replaced by that cleaned
    # match here, even if a caller passed the surrounding text in.
    # Only when no code matches at all (a malformed candidate such
    # as an unknown org) is the stripped input kept, so the failure
    # itself is still visible instead of being silently dropped.
    # Because raw_text is clean by this point, the corrected_code
    # fallback below (``or raw_text``) can never echo a whole row.
    cleaned = extract_first_clean_code(raw_text) if raw_text else None
    if cleaned:
        raw_text = cleaned
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
        "standard_name": None,
        "organization": parsed.get("org_normalized") or parsed.get("org_prefix"),
        "main_number": parsed.get("std_main_number"),
        "year": parsed.get("std_year"),
        "parts": parts,
        "suffix": parsed.get("suffix"),
        "confidence_score": _float_score(parsed.get("confidence_score", 0.0)),
        "verified": bool(verified),
        "explanation": explanation or "",
    }


def _expand_record(record: dict, parsed: dict | None) -> list[dict]:
    """Expand one range/list record into one record per part.

    The parser marks a record expandable via
    ``parsed["expanded_parts"]`` when its parts came from an
    explicit range (``1 đến 10``, ``1-10`` in a part note), an
    explicit list (``các phần 1, 2, 5, 6, 7``), or a bare hyphen
    code ``MAIN-A-B`` with B > A, which the user's catalog rule
    reads as a range A..B (``ISO 9001-1-10:2015`` ->
    ``ISO 9001-1:2015`` … ``ISO 9001-10:2015``; ``EN 1993-1-10``
    -> ``EN 1993-1`` … ``EN 1993-10``). A missing field is simply
    left out, never invented: no year, no part, or no equivalent
    in the input means none in the expanded records either.
    Codes that do not expand: a single part, a degenerate
    ``1-1`` (B == A), and codes with any number of parts other
    than two. Note the trade-off the user accepted: a bare
    ``4-41`` code now also expands to 4..41, even though in
    international numbering some such codes are a single
    hierarchical document; the catalog rule overrides that reading.

    Each expanded record keeps the original's organization, main
    number, year, suffix, confidence and verified flag, but has
    exactly one part: ``raw_text`` is the expanded code as written
    in the source (original org, e.g. ``BS EN``), ``corrected_code``
    is the same code with the normalized org (e.g. ``EN``), and
    ``standard_name`` -- when present -- is re-split per part, so
    a part-list title also yields only its own part's title.
    The original range/list is noted in ``explanation`` so the
    expansion is traceable. Returns ``[record]`` unchanged when
    the record is not expandable, or when an AI correction changed
    the code so the original parsed parts no longer describe it.
    """
    if not parsed:
        return [record]
    expanded = parsed.get("expanded_parts") or []
    if len(expanded) < 2:
        return [record]
    canonical = build_canonical_code(parsed)
    if (
        canonical
        and record.get("corrected_code")
        and record["corrected_code"] != canonical
        and record["corrected_code"] != record.get("raw_text")
    ):
        return [record]
    original_parts = record.get("parts")
    note = (
        f" Expanded from parts {original_parts} into "
        f"{len(expanded)} separate part records."
        if original_parts
        else f" Expanded into {len(expanded)} separate part records."
    )
    base_explanation = record.get("explanation") or ""
    records = []
    for part in expanded:
        single_parsed = dict(parsed)
        single_parsed["std_parts"] = [part]
        single_parsed["std_part"] = f"-{part}"
        expanded_record = dict(record)
        expanded_record["parts"] = part
        expanded_record["corrected_code"] = (
            build_canonical_code(single_parsed) or record["corrected_code"]
        )
        expanded_record["raw_text"] = (
            build_canonical_code(
                single_parsed,
                org=parsed.get("org_prefix") or parsed.get("org_normalized"),
            )
            or expanded_record["corrected_code"]
        )
        if record.get("standard_name"):
            expanded_record["standard_name"] = standard_name_for_parts(
                record["standard_name"], {"std_parts": [part]}
            )
        expanded_record["explanation"] = (base_explanation + note).strip()
        records.append(expanded_record)
    return records


def process_candidate(raw_text: str, *, use_ai_fallback: bool = True,
                      ai_suggester=None) -> dict:
    """Process one candidate string through parse -> (optional) Gemini -> JSON.

    ``raw_text`` here must be a code, but callers sometimes pass a
    whole row or paragraph string by mistake. To make that harmless,
    the first cleaned standard-code match in the input (if any) is
    extracted and used as the candidate from here on, so both
    ``raw_text`` and the parser input are just the code, never the
    surrounding description. The Gemini suggester therefore also
    receives only the code. When no code matches, the stripped
    input is kept as-is so a malformed candidate is not lost.
    """
    raw_text = (raw_text or "").strip()
    cleaned = extract_first_clean_code(raw_text)
    if cleaned:
        raw_text = cleaned
    parsed = parse_standard_code(raw_text)

    equivalent = parsed.get("equivalent_text")
    equivalent_note = (
        f" Equivalent in parentheses: {equivalent} (kept as a separate "
        "code in text/document runs; its year is not this code's year)."
        if equivalent else ""
    )

    if parsed.get("verified"):
        return _record_from_parsed(
            raw_text, parsed, verified=True,
            explanation="Deterministic parse passed (confidence >= 0.8); no AI correction applied."
                        + equivalent_note,
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
            explanation=f"Deterministic parse below threshold (confidence < 0.8); AI fallback not enabled{detail}."
                        + equivalent_note,
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
            ) + equivalent_note,
        )
    except GeminiRequestError as exc:
        return _record_from_parsed(
            raw_text, parsed, verified=False,
            explanation=(
                f"AI fallback failed (Gemini request error: {exc}); "
                "kept deterministic result."
            ) + equivalent_note,
        )
    except Exception as exc:  # never let one bad candidate kill the run
        return _record_from_parsed(
            raw_text, parsed, verified=False,
            explanation=f"AI fallback failed ({exc}); kept deterministic result."
                        + equivalent_note,
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


def process_candidate_expanded(raw_text: str, *, use_ai_fallback: bool = True,
                               ai_suggester=None) -> list[dict]:
    """Like :func:`process_candidate`, but expanding range/list codes.

    Returns one record per part for an expandable range/list code
    (see :func:`_expand_record`), and a single-element list
    otherwise. ``process_candidate`` itself stays single-record for
    backward compatibility; :func:`process_text` and
    :func:`process_document` use this expanded form.
    """
    record = process_candidate(
        raw_text, use_ai_fallback=use_ai_fallback, ai_suggester=ai_suggester)
    # Re-parse deterministically for the expansion provenance.
    # This adds no Gemini call: it only reads parsed["expanded_parts"].
    cleaned = extract_first_clean_code(raw_text) or (raw_text or "").strip()
    return _expand_record(record, parse_standard_code(cleaned))


def _inner_codes_from_parentheticals(raw_text: str) -> list[str]:
    """Codes inside parentheses of an outer candidate (see extractor).

    The outer STANDARD_CODE_PATTERN match consumes the whole
    compound string, so without this the equivalent code inside
    the parentheses would never be processed as its own record.
    """
    inner = []
    outer_key = re.sub(r"\s+", " ", raw_text).strip().upper()
    for note in re.findall(r"\(([^)]*)\)", raw_text or ""):
        for match in STANDARD_CODE_BASE_PATTERN.finditer(note):
            code = clean_code_candidate(match.group("code"))
            if code and re.sub(r"\s+", " ", code).strip().upper() != outer_key:
                inner.append(code)
    if "(" in (raw_text or "") and raw_text.count("(") > raw_text.count(")"):
        tail = raw_text.rsplit("(", 1)[-1]
        for match in STANDARD_CODE_BASE_PATTERN.finditer(tail):
            code = clean_code_candidate(match.group("code"))
            if code and re.sub(r"\s+", " ", code).strip().upper() != outer_key:
                inner.append(code)
    return inner


def process_text(text: str, *, use_ai_fallback: bool = True, ai_suggester=None) -> list[dict]:
    """Extract candidates from a plain-text string and process each one.

    Range/list codes are expanded into one record per part (see
    :func:`_expand_record`). Expanded codes are deduplicated by
    corrected_code, so a part that appears both inside a range and
    as its own code is emitted only once.
    """
    seen = set()
    seen_expanded = set()
    records = []

    def _append_expanded(expanded):
        if len(expanded) > 1:
            for record in expanded:
                if record["corrected_code"] in seen_expanded:
                    continue
                seen_expanded.add(record["corrected_code"])
                records.append(record)
        elif expanded:
            # A single record that was already emitted as part of
            # an earlier range is a duplicate of that part.
            if expanded[0]["corrected_code"] in seen_expanded:
                return
            records.append(expanded[0])

    def _add(raw):
        key = re.sub(r"\s+", " ", raw).strip().upper()
        if not raw or key in seen:
            return
        seen.add(key)
        _append_expanded(process_candidate_expanded(
            raw, use_ai_fallback=use_ai_fallback, ai_suggester=ai_suggester))

    for match in STANDARD_CODE_PATTERN.finditer(text or ""):
        matched_code = match.group("code")
        raw = clean_code_candidate(matched_code)
        _add(raw)
        for inner_code in _inner_codes_from_parentheticals(matched_code):
            _add(inner_code)
    return records


def process_document(file_path, *, use_ai_fallback: bool = True, ai_suggester=None) -> list[dict]:
    """Run the full pipeline over one PDF / DOCX / Excel file.

    Ingestion itself is always deterministic (``use_ai_fallback=False``
    there) so Gemini, when enabled, is called exactly once per
    unverified candidate in this stage -- not once per raw occurrence.
    """
    candidates = extract_standard_codes(file_path, use_ai_fallback=False)
    records = []
    seen_expanded = set()
    for item in candidates:
        # Only the extractor's cleaned "code" field is ever used.
        # There is deliberately NO fallback to a "raw_text" field:
        # a fallback here is exactly how a whole row/paragraph
        # string used to become the output raw_text. Items without
        # a cleaned code are skipped, not emitted with row text.
        raw = item.get("code") or ""
        if not raw:
            continue
        parsed = item.get("parsed")
        if parsed is not None and parsed.get("verified"):
            equivalent = parsed.get("equivalent_text")
            record = _record_from_parsed(
                raw, parsed, verified=True,
                explanation="Deterministic parse passed (confidence >= 0.8); no AI correction applied."
                            + (f" Equivalent in parentheses: {equivalent} (kept as a separate "
                               "code in text/document runs; its year is not this code's year)."
                               if equivalent else ""),
            )
            record["standard_name"] = item.get("standard_name")
            expanded = _expand_record(record, parsed)
        else:
            # Reuse process_candidate for the threshold + Gemini logic.
            record = process_candidate(
                raw, use_ai_fallback=use_ai_fallback, ai_suggester=ai_suggester)
            record["standard_name"] = item.get("standard_name")
            expanded = _expand_record(record, parsed)
        # Range/list codes expand into one record per part, and
        # expanded codes are deduplicated, as in process_text.
        if len(expanded) > 1:
            for record in expanded:
                if record["corrected_code"] in seen_expanded:
                    continue
                seen_expanded.add(record["corrected_code"])
                records.append(record)
        elif expanded:
            if expanded[0]["corrected_code"] in seen_expanded:
                continue
            records.append(expanded[0])
    return records


def _export_excel(records, output_path) -> Path:
    """Lazy Excel export, so a missing openpyxl does not break JSON runs."""
    try:
        from src.exporter.excel_exporter import export_to_excel
    except ModuleNotFoundError:
        try:
            from exporter.excel_exporter import export_to_excel  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "Excel export requires openpyxl; install project dependencies "
                "(see requirements.txt)"
            ) from exc
    except ImportError as exc:
        raise RuntimeError(
            "Excel export requires openpyxl; install project dependencies "
            "(see requirements.txt)"
        ) from exc
    return export_to_excel(records, output_path)


def _ensure_parent_dir(output_path: Path) -> None:
    """Create the output file's parent directory if it does not exist.

    This is the fix for FileNotFoundError on output paths whose
    directory does not exist yet, e.g. ``output/ket_qua.xlsx`` on
    any OS, or a Windows root-relative path such as
    ``\\tmp\\ket_qua.xlsx`` (which is the root of the current drive,
    not the current directory -- prefer a plain relative name
    instead, see below).

    Path handling, explicitly:
      - ``ket_qua.xlsx`` (no directory): parent is ``.``, i.e. the
        current working directory where the user ran the command.
        Nothing is created; the file is written straight into cwd.
        No hardcoded ``/tmp`` or ``\\tmp`` path is used anywhere.
      - ``output/ket_qua.xlsx``: parent ``output`` is created with
        ``parents=True`` (nested parents too) before any writing,
        so writing never fails just because the folder is new.
      - An absolute path is used as-is (it is the user's choice).

    Raises RuntimeError with a clear message if the directory
    cannot be created (e.g. no permission to create a root folder
    on Windows), instead of letting a later write fail with a
    bare FileNotFoundError.
    """
    parent = output_path.parent
    if str(parent) in ("", "."):
        return
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(
            f"Could not create output directory {parent}: {exc}. "
            "Use a relative file name such as ket_qua.xlsx, or a "
            "directory you have permission to create."
        ) from exc


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
    parser.add_argument("-o", "--output",
                        help="Write results to this file instead of stdout: "
                             ".xlsx for a formatted Excel file with exactly 7 columns "
                             "(see src/exporter/excel_exporter.py), .json for JSON, "
                             "any other extension is written as Excel format.")
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
        output_path = Path(args.output)
        # Create the parent directory FIRST, for both formats.
        # Previously only the Excel exporter did this internally,
        # and the JSON branch called write_text() directly, which
        # raises FileNotFoundError when the directory does not
        # exist (e.g. output/ket_qua.xlsx with no output/ folder).
        try:
            _ensure_parent_dir(output_path)
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        if output_path.suffix.lower() == ".json":
            # JSON is text: write_text() is correct here.
            output_path.write_text(payload, encoding="utf-8")
        else:
            # Excel (.xlsx) is a binary ZIP file: it must NEVER be
            # written with write_text(), which would corrupt it.
            # export_to_excel() writes it with openpyxl's
            # workbook.save() (binary) only.
            try:
                created = _export_excel(records, output_path)
            except RuntimeError as exc:
                print(f"Error: {exc}", file=sys.stderr)
                return 1
            print(f"Excel file successfully created: {created}")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
