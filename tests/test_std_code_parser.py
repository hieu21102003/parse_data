# tests/test_std_code_parser.py

import pytest
from decimal import Decimal


from parsers.std_code_parser import (
    parse_standard_code,
    normalize_text,
    normalize_org,
    split_parts,
)


# =====================================================
# NORMALIZE TEXT
# =====================================================

def test_normalize_text_basic():
    assert normalize_text("  TCVN 1234:2020  ") == "TCVN 1234:2020"


def test_normalize_text_tabs_newlines():
    raw = "TCVN\t1234:\n2020"
    assert normalize_text(raw) == "TCVN 1234:2020"


def test_normalize_text_nbsp():
    raw = "TCVN\xa01234:2020"
    assert normalize_text(raw) == "TCVN 1234:2020"


def test_normalize_text_colon_spacing():
    raw = "TCVN 1234 : 2020"
    assert normalize_text(raw) == "TCVN 1234:2020"


# =====================================================
# SPLIT PARTS
# =====================================================

def test_split_parts_none():
    assert split_parts(None) == []


def test_split_parts_single():
    assert split_parts("-1") == ["1"]


def test_split_parts_multi():
    assert split_parts("-4-41") == ["4", "41"]


# =====================================================
# NORMALIZE ORG
# =====================================================

def test_normalize_org_exact():
    org, conf = normalize_org("TCVN")
    assert org == "TCVN"
    assert conf == 1.0


def test_normalize_org_with_slash():
    org, conf = normalize_org("TCVN/ISO")
    assert org == "TCVN"
    assert conf == 1.0


def test_normalize_org_en_iso():
    org, conf = normalize_org("EN ISO")
    assert org == "ISO"
    assert conf == 1.0


def test_normalize_org_heuristic():
    # ASTM is now a known org (see ORG_MAP), so the heuristic case uses
    # a genuinely unknown body instead of "ASTM D".
    org, conf = normalize_org("XYZ Q")
    assert org == "XYZ"
    assert conf == 0.7


def test_normalize_org_astm_exact():
    org, conf = normalize_org("ASTM")
    assert org == "ASTM"
    assert conf == 1.0


def test_normalize_org_unknown():
    org, conf = normalize_org("???")
    assert org == "???"
    assert conf == 0.4


# =====================================================
# PARSER - BASIC
# =====================================================

def test_parse_simple_code():
    r = parse_standard_code("TCVN 1234:2020")

    assert r["org_prefix"] == "TCVN"
    assert r["org_normalized"] == "TCVN"
    assert r["std_main_number"] == "1234"
    assert r["series_number"] == "1234"
    assert r["std_code_full"] == "1234"
    assert r["std_year"] == 2020
    assert r["confidence_score"] == Decimal("0.8")


# =====================================================
# PARSER - MULTI PART
# =====================================================

def test_parse_multi_part():
    r = parse_standard_code("TCVN 7447-4-41:2010")

    assert r["std_parts"] == ["4", "41"]
    assert r["std_code_full"] == "7447-4-41"


# =====================================================
# PARSER - DIRTY INPUT
# =====================================================

def test_parse_with_extra_spaces():
    r = parse_standard_code("TCVN  9366-1: 2012")

    assert r["std_code_full"] == "9366-1"
    assert r["std_year"] == 2012


def test_parse_with_line_break():
    r = parse_standard_code("TCVN 7161-\n13:2024")

    assert r["std_code_full"] == "7161-13"


# =====================================================
# PARSER - SUFFIX / AMENDMENT
# =====================================================

def test_parse_with_suffix():
    r = parse_standard_code("TCCS 37:2022/TCĐBVN")

    assert r["suffix"] == "TCĐBVN"


def test_parse_with_amendment():
    r = parse_standard_code("EN 1994-1-1:2004/AC:2009")

    assert r["amendment"] is not None
    assert "AC" in r["amendment"]


# =====================================================
# PARSER - VERSION TEXT
# =====================================================

def test_parse_with_version_text():
    r = parse_standard_code("TCVN 1234:2020 (rev 1)")

    assert r["version_text"] == "rev 1"


# =====================================================
# PARSER - ORG NORMALIZATION IMPACT
# =====================================================

def test_parse_org_normalization():
    r = parse_standard_code("EN ISO 1234:2020")

    assert r["org_normalized"] == "ISO"


# =====================================================
# PARSER - INVALID INPUT
# =====================================================

def test_parse_invalid():
    r = parse_standard_code("INVALID STRING")

    assert r["std_main_number"] is None
    assert r["confidence_score"] == 0.0


# =====================================================
# CONFIDENCE
# =====================================================

def test_confidence_high():
    r = parse_standard_code("TCVN 1234:2020")
    assert r["confidence_score"] == Decimal("0.8")


def test_confidence_low():
    r = parse_standard_code("???")
    assert r["confidence_score"] < 0.5