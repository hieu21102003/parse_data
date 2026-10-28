"""Regression tests for patterns from a real foreign-standards Excel list.

These were all score 0.0 / all-null before the year-optional parser fix:
year by hyphen/slash, year missing entirely, no space between org and
number, series letters, decimal mains, and ASTM/AASHTO short years.
Run with: PYTHONPATH=src python -m pytest tests/test_pipeline_real_world.py -q
"""

import pytest

try:
    from parsers.std_code_parser import parse_standard_code
except ModuleNotFoundError:  # pragma: no cover - repo-root PYTHONPATH
    from src.parsers.std_code_parser import parse_standard_code  # type: ignore


@pytest.mark.parametrize("raw,org,main,year,parts", [
    ("GB 50157-2003", "GB", "50157", 2003, []),
    ("EN 1337-1/2011", "EN", "1337", 2011, ["1"]),
    ("EN 50172/2004", "EN", "50172", 2004, []),
    ("EN 50122-1-2011", "EN", "50122", 2011, ["1"]),
    ("BS EN 50132-7/1996", "BS EN", "50132", 1996, ["7"]),
    ("IEC 60850/2007-02", "IEC", "60850", 2007, []),
    ("DIN EN 13230-1-2009", "EN", "13230", 2009, ["1"]),
    ("JIS E 3013-2001", "JIS", "3013", 2001, []),
    ("AASHTO M297-2006", "AASHTO", "297", 2006, []),
    ("IEEE Std 1474.1-2004", "IEEE", "1474.1", 2004, []),
    ("IEEE-Std 802.11-1997", "IEEE", "802.11", 1997, []),
])
def test_year_via_hyphen_or_slash_is_verified(raw, org, main, year, parts):
    r = parse_standard_code(raw)
    assert r["org_normalized"] == org
    assert r["std_main_number"] == main
    assert r["std_year"] == year
    assert r["std_parts"] == parts
    assert r["verified"] is True


@pytest.mark.parametrize("raw,org,main,parts", [
    ("EN 50129", "EN", "50129", []),
    ("EN 13803-1", "EN", "13803", ["1"]),
    ("IEC 60529", "IEC", "60529", []),
    ("IEC 60364-4-41", "IEC", "60364", ["4", "41"]),
    ("TCVN 4756", "TCVN", "4756", []),
    ("DIN EN 1537", "EN", "1537", []),
    ("IEEE 802.11", "IEEE", "802.11", []),
    ("JIS E 1102", "JIS", "1102", []),
    ("ASTM D412", "ASTM", "412", []),
    ("ASTM C 665", "ASTM", "665", []),
    ("JISC1731-2", "JIS", "1731", ["2"]),
    ("Ulc 779-9", "ULC", "779", ["9"]),
    ("ASME B1.20.7", "ASME", "1.20.7", []),
    ("ANSI A 108.1", "ANSI", "108.1", []),
])
def test_year_missing_still_populates_fields(raw, org, main, parts):
    r = parse_standard_code(raw)
    assert r["org_normalized"] == org
    assert r["std_main_number"] == main
    assert r["std_parts"] == parts
    assert r["std_year"] is None
    # Without a year it cannot reach 0.8, but it must not be all-null 0.0.
    assert r["confidence_score"] > 0
    assert r["verified"] is False


def test_year_missing_with_colon_year_is_verified():
    r = parse_standard_code("IEC62278:2002")
    assert r["std_year"] == 2002
    assert r["verified"] is True


@pytest.mark.parametrize("raw,main,year", [
    ("ASTM D 4719-07", "4719", 2007),
    ("ASTM D 4767-11", "4767", 2011),
    ("AASHTO T27-99", "27", 1999),
    ("ASTM C172-04", "172", 2004),
    ("GBJ 22-87", "22", 1987),
])
def test_short_edition_year_for_astm_aashto_gbj(raw, main, year):
    r = parse_standard_code(raw)
    assert r["std_main_number"] == main
    assert r["std_year"] == year


@pytest.mark.parametrize("raw,parts", [
    ("JIS B8009-12", ["12"]),
    ("EN 301489-18", ["18"]),
    ("EN 45545-1-7", ["1", "7"]),
])
def test_trailing_two_digit_group_is_part_not_year(raw, parts):
    r = parse_standard_code(raw)
    assert r["std_parts"] == parts
    assert r["std_year"] is None
