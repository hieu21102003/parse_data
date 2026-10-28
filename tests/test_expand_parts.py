"""Part-range/list expansion into one record per part.

See PIPELINE.md "Part expansion" for the full rule. An explicit
range ("1 đến 10", "1-10" in a part note, "từ 1 đến 10"), an
explicit list in a part note ("các phần 1, 2, 5, 6, 7"), and
a comma list written after the first part ("MAIN-1,2,3,4,5")
all expand. A complete code is org + main + part + year +
optional equivalent; a missing field is simply left out, never
invented. What does NOT expand: a bare hyphen code "MAIN-A-B"
with no range/list words -- per the standard's numbering it is
Part A, Chapter B, a single document (e.g. "EN 1993-1-10" is
Part 1, Chapter 10, and "TCVN 7447-4-41:2010" is Part 4,
Chapter 41) -- a single part, and a degenerate "1-1".
An earlier version expanded bare hyphen codes as ranges; that
was wrong and was reverted.
"""

import pytest

from pipeline import process_candidate, process_document, process_text
from parsers.std_code_parser import parse_standard_code


def test_parser_marks_range_and_list_for_expansion():
    range_parsed = parse_standard_code("BS EN 13146-1 đến 10:2019")
    assert range_parsed["std_parts"] == ["1", "10"]
    assert range_parsed["parts_kind"] == "range"
    assert range_parsed["expanded_parts"] == [str(n) for n in range(1, 11)]

    list_parsed = parse_standard_code("EN 13481 (các phần 1, 2, 5, 6, 7)")
    assert list_parsed["std_parts"] == ["1", "2", "5", "6", "7"]
    assert list_parsed["parts_kind"] == "list"
    assert list_parsed["expanded_parts"] == ["1", "2", "5", "6", "7"]


def test_parser_marks_comma_list_for_expansion():
    # Comma list written after the first part, with the year
    # after the list still parsed as the year.
    parsed = parse_standard_code("TCVN 13566-1,2,3,4,5:2022")
    assert parsed["std_parts"] == ["1", "2", "3", "4", "5"]
    assert parsed["std_year"] == 2022
    assert parsed["parts_kind"] == "list"
    assert parsed["expanded_parts"] == ["1", "2", "3", "4", "5"]

    parsed = parse_standard_code("TCVN 13566-1, 2, 3, 4 và 5:2022")
    assert parsed["std_parts"] == ["1", "2", "3", "4", "5"]
    assert parsed["std_year"] == 2022
    assert parsed["parts_kind"] == "list"


def test_parser_does_not_mark_bare_hyphen_for_expansion():
    # Bare hyphen codes are Part A, Chapter B, a single
    # document -- NOT a range. This reverts PR #11, which
    # expanded them as ranges.
    for text, parts in (
        ("ISO 9001-1-10:2015", ["1", "10"]),
        ("EN 1993-1-10", ["1", "10"]),
        ("BS EN 13146-1-10", ["1", "10"]),
        ("TCVN 7447-4-41:2010", ["4", "41"]),
    ):
        parsed = parse_standard_code(text)
        assert parsed["std_parts"] == parts
        assert parsed["parts_kind"] is None
        assert parsed["expanded_parts"] is None


def test_parser_does_not_expand_degenerate_or_other_part_counts():
    # B == A is degenerate, not a range.
    eurocode = parse_standard_code("EN 1994-1-1:2004/AC:2009")
    assert eurocode["std_parts"] == ["1", "1"]
    assert eurocode["expanded_parts"] is None

    single = parse_standard_code("TCVN 13695-1:2023")
    assert single["std_parts"] == ["1"]
    assert single["expanded_parts"] is None


def test_process_text_expands_user_range_example():
    records = process_text("BS EN 13146-1 đến 10:2019", use_ai_fallback=False)
    assert len(records) == 10
    # Both raw_text and corrected_code keep the org as written
    # (BS EN): the combined prefix is preserved, not reduced to EN.
    assert [r["raw_text"] for r in records] == [
        f"BS EN 13146-{n}:2019" for n in range(1, 11)
    ]
    assert [r["corrected_code"] for r in records] == [
        f"BS EN 13146-{n}:2019" for n in range(1, 11)
    ]
    assert [r["parts"] for r in records] == [str(n) for n in range(1, 11)]
    assert all(r["year"] == 2019 for r in records)
    assert all(r["verified"] for r in records)
    assert "Expanded from parts 1-10 into 10 separate part records." in records[0]["explanation"]


def test_process_text_expands_discontinuous_list_without_inventing_parts():
    records = process_text("EN 13481 (các phần 1, 2, 5, 6, 7)", use_ai_fallback=False)
    assert [r["corrected_code"] for r in records] == [
        "EN 13481-1", "EN 13481-2", "EN 13481-5", "EN 13481-6", "EN 13481-7",
    ]
    # No year was in the input, so none is invented.
    assert all(r["year"] is None for r in records)


def test_process_text_expands_parenthetical_and_vietnamese_ranges():
    records = process_text("TCVN 13566:2022 (các phần 1-6)", use_ai_fallback=False)
    assert [r["corrected_code"] for r in records] == [
        f"TCVN 13566-{n}:2022" for n in range(1, 7)
    ]

    records = process_text("TCVN 13566 từ 1 đến 10:2019", use_ai_fallback=False)
    assert len(records) == 10
    assert records[-1]["corrected_code"] == "TCVN 13566-10:2019"


def test_process_text_keeps_suffix_on_every_expanded_part():
    records = process_text("EN 1994-1 đến 3:2004/AC:2009", use_ai_fallback=False)
    assert [r["corrected_code"] for r in records] == [
        f"EN 1994-{n}:2004/AC:2009" for n in range(1, 4)
    ]
    assert all(r["suffix"] == "AC:2009" for r in records)


def test_process_text_expands_comma_list():
    # The previously failing form: a comma list after the
    # first part used to yield only part 1 and lose the year.
    records = process_text("TCVN 13566-1,2,3,4,5:2022", use_ai_fallback=False)
    assert [r["corrected_code"] for r in records] == [
        f"TCVN 13566-{n}:2022" for n in range(1, 6)
    ]
    assert all(r["year"] == 2022 for r in records)

    records = process_text("EN 13481-1,2,3,4,5", use_ai_fallback=False)
    assert [r["corrected_code"] for r in records] == [
        f"EN 13481-{n}" for n in range(1, 6)
    ]
    assert all(r["year"] is None for r in records)


def test_process_text_keeps_bare_hyphen_single():
    # Bare hyphen codes stay single records: Part A, Chapter B.
    # This is the PR #11 revert, verified on the codes that
    # PR #11 wrongly expanded.
    for text, code, parts in (
        ("ISO 9001-1-10:2015", "ISO 9001-1-10:2015", "1-10"),
        ("EN 1993-1-10", "EN 1993-1-10", "1-10"),
        ("TCVN 7447-4-41:2010", "TCVN 7447-4-41:2010", "4-41"),
    ):
        records = process_text(text, use_ai_fallback=False)
        assert len(records) == 1
        assert records[0]["corrected_code"] == code
        assert records[0]["parts"] == parts


def test_process_text_keeps_comma_separated_codes_separate():
    # A comma between two full codes is not a part list.
    records = process_text("TCVN 1234:2020, TCVN 5678:2021", use_ai_fallback=False)
    assert [r["corrected_code"] for r in records] == [
        "TCVN 1234:2020", "TCVN 5678:2021",
    ]


def test_process_text_keeps_degenerate_code_single():
    records = process_text("EN 1994-1-1:2004/AC:2009", use_ai_fallback=False)
    assert len(records) == 1
    assert records[0]["corrected_code"] == "EN 1994-1-1:2004/AC:2009"
    assert records[0]["parts"] == "1-1"


def test_process_text_complete_code_with_equivalent():
    # A complete code: org + main + part + year + equivalent.
    # The equivalent is its own record with its own year, and a
    # missing field (here: the equivalent has no part list beyond
    # its single part) is simply left out, never invented.
    records = process_text(
        "TCVN 13695-1:2023 (BS EN 13146-1:2019)", use_ai_fallback=False)
    by_code = {r["corrected_code"]: r for r in records}
    assert by_code["TCVN 13695-1:2023"]["year"] == 2023
    assert by_code["TCVN 13695-1:2023"]["parts"] == "1"
    assert by_code["BS EN 13146-1:2019"]["year"] == 2019
    assert by_code["BS EN 13146-1:2019"]["parts"] == "1"


def test_process_candidate_stays_single_record_for_compatibility():
    record = process_candidate("BS EN 13146-1 đến 10:2019", use_ai_fallback=False)
    assert record["corrected_code"] == "BS EN 13146-1-10:2019"
    assert record["parts"] == "1-10"


def test_oversized_range_is_not_expanded():
    parsed = parse_standard_code("TCVN 1234-1 đến 200:2020")
    assert parsed["expanded_parts"] is None
    records = process_text("TCVN 1234-1 đến 200:2020", use_ai_fallback=False)
    assert len(records) == 1


def test_process_text_deduplicates_a_part_inside_and_outside_a_range():
    records = process_text(
        "TCVN 13566-1 đến 3:2020 và TCVN 13566-2:2020.", use_ai_fallback=False)
    assert [r["corrected_code"] for r in records] == [
        "TCVN 13566-1:2020", "TCVN 13566-2:2020", "TCVN 13566-3:2020",
    ]


def test_process_document_expands_range_and_splits_part_titles(tmp_path):
    import pandas as pd

    title = (
        "Cầu đường sắt khổ 1435, tốc độ đến 350 km/h - Phần 1: Quy định chung, "
        "Phần 2: Thiết kế tổng thể và tải trọng tác động, "
        "Phần 3: Tải trọng tác động"
    )
    path = tmp_path / "parts.xlsx"
    pd.DataFrame(
        [["TCVN 13594-1 đến 3:2022", title], ["TCVN 13594-2:2022", title]]
    ).to_excel(str(path), index=False, header=False)

    records = process_document(str(path), use_ai_fallback=False)
    # The range expands to 3 parts, and the later single part 2
    # is a duplicate of an expanded part, so it is not repeated.
    assert [r["corrected_code"] for r in records] == [
        "TCVN 13594-1:2022", "TCVN 13594-2:2022", "TCVN 13594-3:2022",
    ]
    # Note: the title cell's comma after "1435" is already dropped
    # by the extractor's title handling (pre-existing, unrelated
    # to expansion); the per-part split itself is what is asserted.
    assert records[0]["standard_name"] == (
        "Cầu đường sắt khổ 1435 tốc độ đến 350 km/h - Phần 1: Quy định chung"
    )
    assert records[1]["standard_name"] == (
        "Cầu đường sắt khổ 1435 tốc độ đến 350 km/h "
        "- Phần 2: Thiết kế tổng thể và tải trọng tác động"
    )
    assert records[2]["standard_name"] == (
        "Cầu đường sắt khổ 1435 tốc độ đến 350 km/h - Phần 3: Tải trọng tác động"
    )
