# parser/std_code_parser.py
#
# Deterministic standard-code parser.
#
# Real-world lists (see tests/test_pipeline_real_world.py) do NOT all use
# the textbook form ``ORG MAIN:YYYY``. Common forms that must at least
# populate org/main (and year when it is present) include:
#   - year optional:            EN 50129, IEC 60529, TCVN 4756
#   - year by hyphen or slash:  GB 50157-2003, EN 1337-1/2011, EN 50172/2004
#   - year by hyphen, part+year: EN 50122-1-2011, DIN EN 13230-1-2009
#   - no space org-number:      IEC62278:2002, IEC60044-1
#   - series letter:            JIS E 1102, ASTM C 665, AASHTO M297-2006,
#                                JISC1731-2, ASTMC117-03
#   - decimal main:             IEEE 802.11, ASME B1.20.7, ANSI A 108.1
#   - short edition year (ASTM/AASHTO/GBJ only): ASTM D 4719-07 -> 2007,
#     AASHTO T27-99 -> 1999, GBJ 22-87 -> 1987. For other bodies a trailing
#     2-digit group is a part (JIS B8009-12, EN 301489-18), NOT a year.
#
# A code without a year can never reach the 0.8 verified threshold
# (org 0.2 + main 0.3 + parts/suffix at most 0.2 = 0.7), so it stays
# unverified and is a Gemini-fallback candidate -- but its fields are
# populated instead of returning all-null with score 0.0.

import re
from decimal import Decimal, ROUND_HALF_UP


# Pipeline rule (see docs/PIPELINE.md): a deterministic parse is treated as
# verified only at this confidence threshold. Anything below it -- or a
# parse failure -- must go through the Gemini fallback, which always
# returns verified=False.
VERIFIED_THRESHOLD = Decimal("0.8")


WHITESPACE_REGEX = re.compile(r"\s+")

# Kept for backward compatibility; parse_standard_code no longer uses a
# single regex because real codes need year-optional, multi-separator
# handling (see _parse_remainder below).
CODE_REGEX = re.compile(
    r"""
    ^(?P<org>[A-Z][A-Z0-9\/\-\s]*?)      # org
    \s+
    (?P<main>\d+(?:\.\d+)?)              # main
    (?P<parts>(?:-\d+)*)                 # -1-2-3
    \s*:\s*
    (?P<year>\d{4})                      # year
    (?P<suffix>.*)?                      # /AC:2009 /TCĐBVN
    """,
    re.VERBOSE
)


# -------------------------------------------------
# ORG NORMALIZATION MAP
# -------------------------------------------------
# Longest-first startswith matching is used in normalize_org, so
# multi-word keys (TCVN/ISO, EN ISO, BS EN, DIN EN) win over their
# single-word prefixes. Adding a body here intentionally makes its
# codes score org 1.0 instead of the 0.7 heuristic -- e.g. ASTM, which
# previously only scored 0.7 for "ASTM D" because the series letter
# was still attached to the org.
ORG_MAP = {
    "TCVN": "TCVN",
    "TCVN/ISO": "TCVN",
    "QCVN": "QCVN",
    "ISO": "ISO",
    "EN": "EN",
    "EN ISO": "ISO",
    "BS EN": "EN",
    "BS": "BS",
    "DIN EN": "EN",
    "DIN ISO": "DIN",
    "DIN": "DIN",
    "IEC": "IEC",
    "TCCS": "TCCS",
    "GB": "GB",
    "JIS": "JIS",
    "ASTM": "ASTM",
    "IEEE": "IEEE",
    "ANSI": "ANSI",
    "ASME": "ASME",
    "AASHTO": "AASHTO",
    "AWWA": "AWWA",
    "API": "API",
    "SAE": "SAE",
    "UL": "UL",
    "ULC": "ULC",
    "ENV": "ENV",
}

_KNOWN_ORG_PREFIXES = (
    "AASHTO", "ASTM", "ASME", "ANSI", "IEEE", "JIS", "IEC", "ISO",
    "DIN", "BS", "GB", "EN",
)

# Bodies whose trailing "-YY" is an edition year, not a part.
_SHORT_YEAR_ORGS = {"ASTM", "AASHTO"}


def normalize_text(text: str) -> str:
    if not text:
        return text

    text = text.replace("\n", "").replace("\r", "")
    text = text.replace("\t", " ").replace("\xa0", " ")

    text = WHITESPACE_REGEX.sub(" ", text)
    text = re.sub(r"\s*:\s*", ":", text)

    return text.strip()


def normalize_org(org: str):
    if not org:
        return None, 0.0

    org_clean = org.strip().upper()
    # "IEEE Std" / "IEEE-Std" is just IEEE; drop the Std token before matching.
    org_clean = re.sub(r"(?:^|[\s\-])STD(?:$|[\s\-])", " ", org_clean)
    org_clean = re.sub(r"\s+", " ", org_clean).strip()
    if not org_clean:
        return None, 0.0

    # -------------------------------------------------
    # STEP 1 — Exact match (LONGEST FIRST)
    # -------------------------------------------------
    for k, v in sorted(ORG_MAP.items(), key=lambda x: -len(x[0])):
        if org_clean.startswith(k):
            return v, 1.0

    # -------------------------------------------------
    # STEP 2 — Heuristic
    # -------------------------------------------------
    org_clean = org_clean.replace("/", " ")

    org_clean = re.sub(r"\s+", " ", org_clean)

    tokens = org_clean.split()

    if tokens:
        candidate = tokens[0]

        if re.match(r"^[A-Z]{2,10}$", candidate):
            return candidate, 0.7

    # -------------------------------------------------
    # STEP 3 — fallback
    # -------------------------------------------------
    return org_clean, 0.4


def split_parts(part_str: str):
    if not part_str:
        return []

    return [p for p in part_str.strip("-").split("-") if p]


def _is_year_token(token: str) -> bool:
    """True for a plausible 4-digit publication year (1900-2100)."""
    return (
        len(token) == 4
        and token.isdigit()
        and 1900 <= int(token) <= 2100
    )


def _short_year(org_normalized, org_prefix, token: str):
    """Convert a trailing 2-digit edition year, or None.

    Only for ASTM/AASHTO (and GBJ, whose ``GBJ 22-87`` form is year
    1987). Pivot 50: 50-99 -> 19xx, 00-49 -> 20xx.
    """
    if len(token) != 2 or not token.isdigit():
        return None
    if org_normalized in _SHORT_YEAR_ORGS or org_prefix == "GBJ":
        yy = int(token)
        return 1900 + yy if yy >= 50 else 2000 + yy
    return None


def _parse_remainder(rest: str, org_normalized, org_prefix):
    """Parse everything after the main number.

    Returns (parts, year, suffix). Parts are hyphen groups that are not
    a year; year may come after ':', '-', '/', or a space; anything
    after a resolved year that is not another year is a suffix.
    """
    parts: list[str] = []
    year = None
    suffix = None
    s = (rest or "").strip()

    while s:
        if s.startswith(":"):
            m = re.match(r":\s*(\d{4})\b(.*)$", s, re.DOTALL)
            if m and year is None and _is_year_token(m.group(1)):
                year = int(m.group(1))
                s = m.group(2).strip()
                continue
            suffix = s
            break
        if s.startswith("/"):
            m = re.match(r"/\s*(\d{4})\b(.*)$", s, re.DOTALL)
            if m and year is None and _is_year_token(m.group(1)):
                year = int(m.group(1))
                s = m.group(2).strip()
                continue
            suffix = s[1:].strip() or None
            break
        if s.startswith("-"):
            if year is not None:
                # e.g. IEC 60850/2007-02, DIN EN 13230-4-2009-10
                suffix = s
                break
            m = re.match(r"-\s*(\d+)(.*)$", s, re.DOTALL)
            if not m:
                suffix = s
                break
            num, after = m.group(1), m.group(2).strip()
            if _is_year_token(num) and year is None:
                year = int(num)
                s = after
                continue
            short = _short_year(org_normalized, org_prefix, num)
            if short is not None and year is None and after in ("",) or (
                short is not None and year is None and after[:1] in ("+", "/", ":")
            ):
                year = short
                s = after
                continue
            parts.append(num)
            s = after
            continue
        if s.startswith("+"):
            suffix = s
            break
        if s.startswith(" "):
            m = re.match(r"\s+(\d{4})\b(.*)$", s)
            if m and year is None and _is_year_token(m.group(1)):
                year = int(m.group(1))
                s = m.group(2).strip()
                continue
            suffix = s.strip() or None
            break
        suffix = s
        break

    return parts, year, suffix


def _extract_series_letter(org_part: str):
    """Split a series letter off the org, e.g. 'JIS E' -> ('JIS', 'E').

    Returns (org_prefix, series_letter). Multi-word orgs such as
    'DIN EN' / 'BS EN' / 'EN ISO' are NOT split (last token > 1 char).
    Merged forms such as 'JISC' / 'ASTMD' / 'AASHTOT' are split when
    the prefix is a known body.
    """
    tokens = org_part.split()
    if len(tokens) >= 2 and len(tokens[-1]) == 1 and tokens[-1].isalpha():
        return " ".join(tokens[:-1]), tokens[-1]
    if len(tokens) == 1:
        token = tokens[0]
        for known in sorted(_KNOWN_ORG_PREFIXES, key=len, reverse=True):
            if token.startswith(known) and len(token) > len(known):
                rest = token[len(known):]
                if rest.isalpha() and len(rest) <= 2:
                    return known, rest
    return org_part, None


# -------------------------------------------------
# CONFIDENCE ENGINE
# -------------------------------------------------
def compute_confidence(result: dict):
    score = Decimal("0.0")
    breakdown = {}

    # org
    org_conf = Decimal(str(result.get("org_confidence", 0)))
    if result.get("org_prefix"):
        val = Decimal("0.2") * org_conf
        score += val
        breakdown["org"] = val

    # main
    if result["std_main_number"]:
        val = Decimal("0.3")
        score += val
        breakdown["main"] = val

    # year
    if result["std_year"]:
        val = Decimal("0.3")
        score += val
        breakdown["year"] = val

    # parts
    if result["std_parts"]:
        val = Decimal("0.1")
        score += val
        breakdown["parts"] = val

    # suffix
    if result["amendment"] or result["suffix"]:
        val = Decimal("0.1")
        score += val
        breakdown["suffix"] = val

    # round to 3 decimal places
    score = score.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

    return score, breakdown


# -------------------------------------------------
# MAIN PARSER
# -------------------------------------------------
def _extract_part_range_from_version(version_text: str) -> list[str]:
    """Extract a part range/list from a parenthetical note, or [].

    Real lists write e.g. ``TCVN 13566:2022 (các phần 1-6)`` or
    ``TCVN 1234:2020 (phần 1 đến 3)``. The note is *not* a version:
    it says which parts the document covers, so dropping it loses
    information. When a part keyword (phần/part) is present, a
    ``1-6`` / ``1 đến 3`` / ``1 to 3`` range becomes ``["1", "6"]``
    (pipeline output joins it back to ``"1-6"``), and a list such as
    ``các phần 1, 3, 5`` becomes ``["1", "3", "5"]``. A bare ``1-6``
    with no keyword is also treated as a part range. The Vietnamese
    range words matter here: ``từ X đến Y`` ("from X to Y") and
    ``-X đến Y`` (leading hyphen = range start, not a negative sign)
    are ranges too, even without the word "phần" and even when a
    year follows in the same note, e.g. ``(từ 1 đến 10, 2019)`` or
    ``(-1 đến 10, 2019)`` -> ``["1", "10"]``. Notes such as
    ``(rev 1)`` or ``(version 2)`` return [] and stay version_text.
    """
    if not version_text:
        return []
    text = version_text.strip().lower()
    has_part_keyword = "phần" in text or "part" in text
    has_range_word = "từ" in text or "đến" in text or "tới" in text
    range_match = re.search(
        r"(\d+)\s*(?:-|–|—|đến|tới|to)\s*(?:phần\s*|part\s*)?(\d+)", text)
    if range_match and (
        has_part_keyword
        or has_range_word
        or re.fullmatch(r"\s*\d+\s*(?:-|–|—)\s*\d+\s*", text)
    ):
        return [range_match.group(1), range_match.group(2)]
    if has_part_keyword:
        numbers = [n for n in re.findall(r"\d+", text) if not _is_year_token(n)]
        return numbers
    return []


def _extract_year_from_version(version_text: str):
    """Return the 4-digit year inside a parenthetical note, or None.

    Used only as a fallback when no year was found outside the
    parentheses, e.g. ``TCVN 13566 (từ 1 đến 10, 2019)`` -> 2019.
    Small part numbers are never mistaken for a year: only a
    1900-2100 token counts.
    """
    if not version_text:
        return None
    for token in re.findall(r"\d{4}", version_text):
        if _is_year_token(token):
            return int(token)
    return None


def _extract_vietnamese_range_from_rest(rest: str):
    """Extract a 'từ X đến Y' / '-X đến Y' range outside parentheses.

    Returns (parts, cleaned_rest). ``rest`` is the uppercase remainder
    after the main number; the pattern is case-insensitive for the
    Vietnamese words. The range segment is removed from the rest so
    a following ``:2019`` / `` 2019`` can still be parsed as the year
    by _parse_remainder. Returns ([], rest) when no such range is present.
    """
    match = re.search(
        r"(?:từ\s*)?-?\s*(\d+)\s*(?:đến|tới)\s*(?:phần\s*)?(\d+)",
        rest or "", re.IGNORECASE)
    if not match:
        return [], rest
    parts = [match.group(1), match.group(2)]
    cleaned = (rest[:match.start()] + rest[match.end():]).strip()
    return parts, cleaned


_EQUIVALENT_ORGS = (
    "TCVN", "QCVN", "TCCS", "ISO", "IEC", "EN", "BS EN", "BS",
    "DIN EN", "DIN", "ASTM", "JIS", "ANSI", "ASME", "IEEE",
    "SAE", "API", "AASHTO", "AWWA", "UL", "GB",
)


def _version_text_is_standard_code(version_text: str) -> bool:
    """True when a parenthetical note is itself a standard code.

    E.g. ``BS EN 13146-1 đến 10:2019`` in
    ``TCVN 13695-1 đến 10:2023 (BS EN 13146-1 đến 10:2019)`` is an
    *equivalent* designation, not a version, part list, or year for
    the outer code. Its main number, parts and year must never be
    stolen as the outer code's parts/year (a previous version did
    exactly that: it could read ``13146-1`` as parts). Such a note
    is returned as ``equivalent_text`` instead.
    """
    if not version_text:
        return False
    upper = version_text.strip().upper()
    if not any(c.isdigit() for c in upper):
        return False
    return any(
        upper == org or upper.startswith(org + " ") or upper.startswith(org + "/")
        for org in _EQUIVALENT_ORGS
    )


def parse_standard_code(raw_code: str) -> dict:
    text = normalize_text(raw_code)

    result = {
        "raw_code": raw_code,
        "normalized_code": text,

        "org_prefix": None,
        "org_normalized": None,
        "org_confidence": 0.0,

        "series_number": None,
        "series_letter": None,

        "std_main_number": None,
        "std_part": None,
        "std_parts": [],
        "std_code_full": None,

        "std_year": None,
        "amendment": None,
        "suffix": None,
        "version_text": None,
        "equivalent_text": None,

        "confidence_score": 0.0,
        "confidence_breakdown": {},
        # Deterministic verification flag. False on a parse failure and
        # until the confidence threshold below is met.
        "verified": False,
    }

    # -------------------------------------------------
    # STEP 1 — VERSION (...)
    # -------------------------------------------------
    version_match = re.search(r"\((.*?)\)", text)
    if version_match:
        result["version_text"] = version_match.group(1).strip()
        text = re.sub(r"\(.*?\)", "", text).strip()
    elif "(" in text:
        # Unclosed parenthetical, e.g. the user's exact string
        # "... (BS EN 13146-1 đến 10:2019" with no closing ")".
        # Without this, the whole equivalent note becomes a suffix
        # and the outer code's corrected_code turns into an ugly
        # ".../(BS EN ..." string.
        before, _, note = text.partition("(")
        result["version_text"] = note.strip().rstrip(")")
        text = before.strip()
    if _version_text_is_standard_code(result["version_text"]):
        result["equivalent_text"] = result["version_text"]

    # -------------------------------------------------
    # STEP 2 — ORG + MAIN (year is optional from here on)
    # -------------------------------------------------
    # Uppercase for matching only: this also fixes "Ulc 779-9" -> ULC.
    upper = text.upper()
    digit_match = re.search(r"\d", upper)
    if not digit_match:
        return result

    org_part = upper[:digit_match.start()].strip()
    if not org_part:
        return result
    org_prefix, series_letter = _extract_series_letter(org_part)
    result["org_prefix"] = org_part
    result["series_letter"] = series_letter
    org_norm, org_conf = normalize_org(org_prefix)
    result["org_normalized"] = org_norm
    result["org_confidence"] = org_conf

    remainder = upper[digit_match.start():].strip()
    main_match = re.match(r"(\d+(?:\.\d+)*)", remainder)
    if not main_match:
        return result
    main = main_match.group(1)
    result["std_main_number"] = main
    result["series_number"] = main
    rest = remainder[len(main):].strip()

    # -------------------------------------------------
    # STEP 3 — PARTS / YEAR / SUFFIX
    # -------------------------------------------------
    # Vietnamese range outside parentheses first, e.g.
    # "TCVN 13566 từ 1 đến 10:2019" -> range ["1", "10"], rest ":2019".
    range_from_rest, rest_cleaned = _extract_vietnamese_range_from_rest(rest)
    parts, year, suffix = _parse_remainder(rest_cleaned, org_norm, org_part)
    if range_from_rest and not parts:
        parts = range_from_rest
    if result["equivalent_text"] is None:
        # Only a plain part/year note may supply the outer code's
        # parts/year. An equivalent code in parentheses must NOT:
        # its "13146-1" is its own main/part, not the outer code's.
        if not parts:
            # Part range/list carried only in the parenthetical note, e.g.
            # "TCVN 13566:2022 (các phần 1-6)" -> parts ["1", "6"].
            parts = _extract_part_range_from_version(result["version_text"])
        if year is None:
            # Year carried only in the parenthetical note, e.g.
            # "TCVN 13566 (từ 1 đến 10, 2019)" -> year 2019, not null.
            # An outside year, when present, always wins (see test).
            year = _extract_year_from_version(result["version_text"])
    result["std_parts"] = parts
    result["std_part"] = ("-" + "-".join(parts)) if parts else None
    result["std_year"] = year

    if suffix:
        suffix = suffix.strip()
        if suffix.startswith("/"):
            suffix = suffix[1:].strip()
        if suffix:
            # A valid suffix is a single token (AC:2009, TCĐBVN,
            # -02, +A1). Multi-word text after the code -- e.g. a
            # description separated by "|", "-" or a space, which
            # _parse_remainder returns verbatim as the suffix --
            # is surrounding prose, not a suffix. Drop it instead
            # of letting it leak into corrected_code via the
            # build_canonical_code() fallback. Single-token suffixes
            # are kept exactly as before.
            if re.search(r"\s", suffix):
                result["suffix"] = None
            else:
                amend_match = re.search(r"(AC|A\d+|AMD\d+):?(\d{4})?", suffix)
                if amend_match:
                    result["amendment"] = amend_match.group(0)
                result["suffix"] = suffix

    # -------------------------------------------------
    # STEP 4 — BUILD FULL CODE (main + parts, as before)
    # -------------------------------------------------
    if result["std_parts"]:
        result["std_code_full"] = (
            main + "-" + "-".join(result["std_parts"])
        )
    else:
        result["std_code_full"] = main

    # -------------------------------------------------
    # STEP 5 — CONFIDENCE
    # -------------------------------------------------
    score, breakdown = compute_confidence(result)

    result["confidence_score"] = score
    result["confidence_breakdown"] = breakdown
    result["verified"] = (
        result["std_main_number"] is not None
        and result["std_year"] is not None
        and score >= VERIFIED_THRESHOLD
    )

    return result


def parse_standard_code_with_ai_fallback(raw_code: str) -> dict:
    """Use Gemini when the deterministic parse is not verified.

    That is: on a parse failure *or* when ``confidence_score < 0.8``.
    The returned structure keeps the normal parser fields and adds AI
    review metadata. A Gemini suggestion is never treated as verified,
    and ``explanation`` is the pipeline-facing alias for Gemini's
    ``reason`` field.
    """
    result = parse_standard_code(raw_code)
    if result.get("verified"):
        result["ai_fallback"] = {"used": False, "verified": True, "explanation": ""}
        return result

    try:
        from src.ai.gemini_standard_normalizer import (
            GeminiConfigurationError,
            GeminiRequestError,
            suggest_standard_code,
        )
    except ModuleNotFoundError:
        # Support running with src/ itself on PYTHONPATH as the existing tests do.
        from ai.gemini_standard_normalizer import (  # type: ignore
            GeminiConfigurationError,
            GeminiRequestError,
            suggest_standard_code,
        )

    try:
        suggestion = suggest_standard_code(raw_code)
    except (GeminiConfigurationError, GeminiRequestError) as exc:
        # Do not crash the caller on a missing key or a network/API
        # failure: report it in ai_fallback instead.
        result["verified"] = False
        result["ai_fallback"] = {
            "used": True,
            "suggestion": None,
            "status": "error",
            "confidence": 0.0,
            "reason": str(exc),
            "explanation": str(exc),
            "alternatives": [],
            "verified": False,
        }
        return result
    candidate = suggestion.get("suggested_code")
    explanation = suggestion.get("explanation") or suggestion.get("reason", "")
    ai_meta = {
        "used": True,
        "suggestion": candidate,
        "status": suggestion.get("status"),
        "confidence": suggestion.get("confidence"),
        "reason": suggestion.get("reason", ""),
        "explanation": explanation,
        "alternatives": suggestion.get("alternatives", []),
        "verified": False,
    }
    if candidate:
        parsed = parse_standard_code(candidate)
        if parsed["std_main_number"] is not None:
            parsed["raw_code"] = raw_code
            parsed["verified"] = False
            parsed["ai_fallback"] = ai_meta
            return parsed

    result["verified"] = False
    result["ai_fallback"] = ai_meta
    return result
