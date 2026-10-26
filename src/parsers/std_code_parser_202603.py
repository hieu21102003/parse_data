# parser/std_code_parser.py

import re


def parse_standard_code(raw_code: str) -> dict:
    text = raw_code.strip()

    result = {
        "raw_code": raw_code,
        "org_prefix": None,
        "std_main_number": None,
        "std_part": None,
        "std_year": None,
        "amendment": None,
        "version_text": None,
    }

    # -------------------------------------------------
    # STEP 1 — Extract VERSION (…)
    # -------------------------------------------------
    version_match = re.search(r"\((.*?)\)", text)
    if version_match:
        result["version_text"] = version_match.group(1).strip()
        text = re.sub(r"\(.*?\)", "", text).strip()

    # -------------------------------------------------
    # STEP 2 — Extract AMENDMENT (+...)
    # -------------------------------------------------
    if "+" in text:
        parts = text.split("+", 1)
        text = parts[0].strip()
        result["amendment"] = parts[1].strip()

    # -------------------------------------------------
    # STEP 3 — Extract ORG PREFIX
    # Everything before the first number is org
    # -------------------------------------------------
    org_match = re.match(r"^([A-Za-z\/\-\s]+?)\s+(?=\d)", text)
    if org_match:
        result["org_prefix"] = org_match.group(1).strip()
        text = text[org_match.end():].strip()

    # -------------------------------------------------
    # STEP 4 — Extract MAIN / PART / YEAR
    # Pattern: 33.501-2:2020
    # -------------------------------------------------
    main_pattern = re.match(
        r"(?P<main>\d+(?:\.\d+)?)"          # 33 or 33.501
        r"(?P<part>-\d+)?"                  # -1
        r":(?P<year>\d{4})",               # :2020
        text
    )

    if main_pattern:
        result["std_main_number"] = main_pattern.group("main")
        result["std_part"] = main_pattern.group("part")
        result["std_year"] = int(main_pattern.group("year"))

    return result

