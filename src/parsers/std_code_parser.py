# parser/std_code_parser.py

import re
from decimal import Decimal, ROUND_HALF_UP


# Pipeline rule (see docs/PIPELINE.md): a deterministic parse is treated as
# verified only at this confidence threshold. Anything below it -- or a
# parse failure -- must go through the Gemini fallback, which always
# returns verified=False.
VERIFIED_THRESHOLD = Decimal("0.8")


WHITESPACE_REGEX = re.compile(r"\s+")

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
ORG_MAP = {
    "TCVN": "TCVN",
    "TCVN/ISO": "TCVN",
    "ISO": "ISO",
    "EN": "EN",
    "EN ISO": "ISO",
    "BS EN": "EN",
    "IEC": "IEC",
    "TCCS": "TCCS"
}


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
def parse_standard_code(raw_code: str) -> dict:
    text = normalize_text(raw_code)

    result = {
        "raw_code": raw_code,
        "normalized_code": text,

        "org_prefix": None,
        "org_normalized": None,
        "org_confidence": 0.0,

        "series_number": None,

        "std_main_number": None,
        "std_part": None,
        "std_parts": [],
        "std_code_full": None,

        "std_year": None,
        "amendment": None,
        "suffix": None,
        "version_text": None,

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

    # -------------------------------------------------
    # STEP 2 — PARSE CORE
    # -------------------------------------------------
    m = CODE_REGEX.match(text)
    if not m:
        return result

    org_raw = m.group("org").strip()
    result["org_prefix"] = org_raw
    org_norm, org_conf = normalize_org(org_raw)
    result["org_normalized"] = org_norm
    result["org_confidence"] = org_conf

    main = m.group("main")
    result["std_main_number"] = main
    result["series_number"] = main  # 🎯 detect series

    part_str = m.group("parts")
    result["std_parts"] = split_parts(part_str)
    result["std_part"] = part_str if part_str else None

    result["std_year"] = int(m.group("year"))

    # -------------------------------------------------
    # STEP 3 — SUFFIX / AMENDMENT
    # -------------------------------------------------
    suffix = (m.group("suffix") or "").strip()

    if suffix.startswith("/"):
        suffix = suffix[1:]

    if suffix:
        amend_match = re.search(r"(AC|A\d+|AMD\d+):?(\d{4})?", suffix)
        if amend_match:
            result["amendment"] = amend_match.group(0)

        result["suffix"] = suffix

    # -------------------------------------------------
    # STEP 4 — BUILD FULL CODE
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
        from src.ai.gemini_standard_normalizer import suggest_standard_code
    except ModuleNotFoundError:
        # Support running with src/ itself on PYTHONPATH as the existing tests do.
        from ai.gemini_standard_normalizer import suggest_standard_code

    suggestion = suggest_standard_code(raw_code)
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
