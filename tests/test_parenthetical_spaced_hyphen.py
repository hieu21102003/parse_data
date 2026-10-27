"""Tests for a parenthetical equivalent whose hyphen is spaced.

The user's exact exception::

    TCVN 4617-1 đến 6:2015(ISO 3452 -1 đến 6)

The equivalent inside the parentheses must be resolved the same
way as the outer code (range 1-6 expanded, no year invented),
while a parenthetical with no standard code of its own::

    TCVN 4617:2015(các phần từ 1 - 6)

is only a part note for the outer code and must produce no
extra record at all.

Detection rule: a parenthetical is an equivalent standard when
it starts with an organisation + main number (the existing
``equivalent_text`` / inner-code handling); otherwise, when it
is a part note (``các phần ...`` / ``phần ...`` / a year), it
supplies the outer code's parts/year only. Before this fix the
spaced hyphen in ``ISO 3452 -1 đến 6`` broke the detection:
the extractor stopped at the main number, the parenthetical
was stripped as prose, and the inner code became a single
bare ``ISO 3452`` record with no parts. The deterministic
parser already handled the spaced hyphen; only the extractor
candidate pattern needed the spaces around ``-`` / ``.`` / ``/``.
"""

try:
    from parsers.std_code_parser import parse_standard_code
except ModuleNotFoundError:  # pragma: no cover - repo-root PYTHONPATH
    from src.parsers.std_code_parser import parse_standard_code  # type: ignore

try:
    from pipeline import process_candidate, process_text
except ModuleNotFoundError:  # pragma: no cover - repo-root PYTHONPATH
    from src.pipeline import process_candidate, process_text  # type: ignore

# The user's exact string: no space before "(", a space before
# the hyphen inside the parentheses, and no year for ISO.
SPACED = "TCVN 4617-1 đến 6:2015(ISO 3452 -1 đến 6)"
SPACED_WITH_SPACE = "TCVN 4617-1 đến 6:2015 (ISO 3452 -1 đến 6)"
SPACED_WITH_YEAR = "TCVN 4617-1 đến 6:2015 (ISO 3452 -1 đến 6:2010)"
SPACED_UNCLOSED = "TCVN 4617-1 đến 6:2015 (ISO 3452 -1 đến 6"
PART_NOTE = "TCVN 4617:2015 (các phần từ 1 - 6)"
PART_NOTE_NO_SPACE = "TCVN 4617:2015(các phần từ 1 - 6)"


def _by_code(records):
    return {r["corrected_code"]: r for r in records}


def test_parser_keeps_spaced_equivalent_as_equivalent_text():
    parsed = parse_standard_code(SPACED_WITH_SPACE)
    assert parsed["std_parts"] == ["1", "6"]
    assert parsed["std_year"] == 2015
    assert parsed["equivalent_text"] == "ISO 3452 -1 đến 6"
    assert parsed["verified"] is True


def test_process_text_expands_spaced_equivalent_like_outer_code():
    for text in (SPACED, SPACED_WITH_SPACE, SPACED_UNCLOSED):
        records = process_text(text, use_ai_fallback=False)
        by_code = _by_code(records)
        # 6 TCVN parts + 6 ISO parts; no bare "ISO 3452" record.
        assert len(records) == 12, records
        assert "ISO 3452" not in by_code
        for part in range(1, 7):
            tcvn = by_code[f"TCVN 4617-{part}:2015"]
            assert tcvn["main_number"] == "4617"
            assert tcvn["year"] == 2015
            assert tcvn["parts"] == str(part)
            assert tcvn["verified"] is True
            iso = by_code[f"ISO 3452-{part}"]
            assert iso["main_number"] == "3452"
            # No year in the source for ISO: left out, never invented.
            assert iso["year"] is None
            assert iso["parts"] == str(part)
            assert iso["verified"] is False


def test_process_text_spaced_equivalent_with_its_own_year():
    records = process_text(SPACED_WITH_YEAR, use_ai_fallback=False)
    by_code = _by_code(records)
    assert len(records) == 12
    for part in range(1, 7):
        assert by_code[f"ISO 3452-{part}:2010"]["year"] == 2010
        assert by_code[f"ISO 3452-{part}:2010"]["verified"] is True
        assert by_code[f"TCVN 4617-{part}:2015"]["year"] == 2015


def test_process_candidate_names_spaced_equivalent():
    record = process_candidate(SPACED_WITH_SPACE, use_ai_fallback=False)
    assert record["corrected_code"] == "TCVN 4617-1-6:2015"
    assert record["year"] == 2015
    assert "ISO 3452 -1 đến 6" in record["explanation"]


def test_part_note_produces_no_extra_record():
    for text in (PART_NOTE, PART_NOTE_NO_SPACE):
        records = process_text(text, use_ai_fallback=False)
        assert len(records) == 6, records
        for part in range(1, 7):
            record = _by_code(records)[f"TCVN 4617-{part}:2015"]
            assert record["main_number"] == "4617"
            assert record["year"] == 2015
            assert record["parts"] == str(part)


def test_spaced_hyphen_on_outer_code_and_comma_list():
    records = process_text(
        "TCVN 4617 -1 đến 6:2015 (ISO 3452-1 đến 6)",
        use_ai_fallback=False,
    )
    assert len(records) == 12
    records = process_text(
        "TCVN 4617-1,2,3:2015 (ISO 3452 -1,2,3)",
        use_ai_fallback=False,
    )
    by_code = _by_code(records)
    assert len(records) == 6
    for part in range(1, 4):
        assert by_code[f"ISO 3452-{part}"]["parts"] == str(part)
        assert by_code[f"ISO 3452-{part}"]["year"] is None


def test_spaced_hyphen_does_not_break_guards():
    # A date range is not a part range, and a bare hyphen code
    # with spaces is still Part 1, Chapter 10, a single record.
    records = process_text("TCVN 1234:2020 đến 2025", use_ai_fallback=False)
    assert len(records) == 1
    assert records[0]["corrected_code"] == "TCVN 1234:2020"
    assert records[0]["parts"] is None
    records = process_text("EN 1993 -1-10", use_ai_fallback=False)
    assert len(records) == 1
    assert records[0]["corrected_code"] == "EN 1993-1-10"
    assert records[0]["parts"] == "1-10"
