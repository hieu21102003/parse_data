# parser/std_code_parser.py

import re


def parse_standard_code(raw_code: str) -> dict:
    """
    Parse raw standard code text into structured fields
    """

    result = {
        "raw_code": raw_code,
        "org_prefix": None,
        "std_main_number": None,
        "std_part": None,
        "std_year": None,
        "amendment": None,
        "version_text": None,
    }

    text = raw_code.strip()

    # Tách amendment (+AMD, /AC, -I1...)
    amend_match = re.findall(r'(\+|/)(AMD|AC|A\d|I\d|ERRATA)[^+\/]*', text)
    if amend_match:
        result["amendment"] = " ".join([m[1] for m in amend_match])

    # Tìm năm chính
    year_match = re.search(r':(\d{4})', text)
    if year_match:
        result["std_year"] = int(year_match.group(1))

    # Tìm org prefix (IEC, EN, IEEE, DIN VDE, 3GPP, AASHTO...)
    org_match = re.match(r'^([A-Z0-9\-\s\/]+?)\s+\d', text)
    if org_match:
        result["org_prefix"] = org_match.group(1).strip()

    # Tìm std number + part
    num_match = re.search(r'(\d+[A-Z\-\.]*\d*(?:-\d+[-\d]*)?)', text)
    if num_match:
        result["std_main_number"] = num_match.group(1)

    # Version text
    version_match = re.search(r'\((.*?)\)', text)
    if version_match:
        result["version_text"] = version_match.group(1)

    return result
