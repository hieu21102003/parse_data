"""Tests for a digit token in the year position that is not a valid year.

The user's screenshot showed rows such as::

    ISO 231123-1/:1231   (confidence < 0.8)

for the source ``ISO 231123-1 đến 10:1231`` (the same happens
for ``:12313`` and ``:9999``; a valid ``:2013`` is clean and
verified). The "/" did not come from the source: the parser
refused ``1231`` as a year (years must be 1900-2100) but kept
``":1231"`` as the suffix, and ``build_canonical_code()``
joins any suffix that does not start with ``-``/``+`` with
``"/"``. A digit token in the year position (after ``:``,
``/``, or a space) that is not a valid year is neither a year
nor a suffix: it is dropped, the code stays unverified with
no year, and no "/" is invented. A following real suffix
(``:1231/AC:2009``) is still parsed.
"""

try:
    from parsers.std_code_parser import parse_standard_code
except ModuleNotFoundError:  # pragma: no cover - repo-root PYTHONPATH
    from src.parsers.std_code_parser import parse_standard_code  # type: ignore

try:
    from pipeline import build_canonical_code, process_candidate, process_text
except ModuleNotFoundError:  # pragma: no cover - repo-root PYTHONPATH
    from src.pipeline import build_canonical_code, process_candidate, process_text  # type: ignore


def test_invalid_year_after_colon_is_neither_year_nor_suffix():
    for text in (
        "ISO 231123-1 đến 10:1231",
        "ISO 231123-1 đến 10:12313",
        "ISO 231123-1 đến 10:9999",
        "ISO 231123-1:1231",
    ):
        parsed = parse_standard_code(text)
        assert parsed["std_year"] is None, text
        assert parsed["suffix"] is None, text


def test_invalid_year_range_expands_without_slash():
    records = process_text(
        "ISO 231123-1 đến 10:1231", use_ai_fallback=False
    )
    assert len(records) == 10
    for part in range(1, 11):
        record = records[part - 1]
        assert record["corrected_code"] == f"ISO 231123-{part}", record
        assert record["raw_text"] == f"ISO 231123-{part}", record
        assert record["year"] is None
        assert record["parts"] == str(part)
        assert record["suffix"] is None
        assert record["verified"] is False
        assert "/:" not in record["corrected_code"]


def test_valid_year_after_colon_still_parses():
    records = process_text(
        "ISO 231123-1 đến 10:2013", use_ai_fallback=False
    )
    assert len(records) == 10
    assert records[0]["corrected_code"] == "ISO 231123-1:2013"
    assert records[0]["year"] == 2013
    assert records[0]["verified"] is True


def test_invalid_year_does_not_swallow_following_suffix():
    record = process_candidate(
        "ISO 231123-1:1231/AC:2009", use_ai_fallback=False
    )
    assert record["corrected_code"] == "ISO 231123-1/AC:2009"
    assert record["suffix"] == "AC:2009"
    assert record["year"] is None


def test_invalid_year_after_slash_and_bare_trailing_number():
    parsed = parse_standard_code("ISO 231123-1/1231")
    assert parsed["std_year"] is None
    assert parsed["suffix"] is None

    parsed = parse_standard_code("ISO 231123-1/2011")
    assert parsed["std_year"] == 2011

    # A bare trailing number after a part: a valid year is the
    # year, an invalid year-sized token is dropped, and a short
    # digit group keeps the existing suffix behaviour.
    parsed = parse_standard_code("TCVN 1234-1 2013")
    assert parsed["std_year"] == 2013
    assert parsed["suffix"] is None
    parsed = parse_standard_code("TCVN 1234 1231")
    assert parsed["std_year"] is None
    assert parsed["suffix"] is None
    parsed = parse_standard_code("TCVN 1234 12")
    assert parsed["suffix"] == "12"


def test_real_suffixes_still_join_with_slash():
    record = process_candidate(
        "EN 1994-1-1:2004/AC:2009", use_ai_fallback=False
    )
    assert record["corrected_code"] == "EN 1994-1-1:2004/AC:2009"
    assert record["suffix"] == "AC:2009"


def test_build_canonical_code_never_joins_colon_suffix_with_slash():
    code = build_canonical_code(
        {
            "std_main_number": "231123",
            "org_normalized": "ISO",
            "std_parts": ["1"],
            "std_year": None,
            "suffix": ":1231",
        }
    )
    assert code == "ISO 231123-1:1231"
    assert "/:" not in code
