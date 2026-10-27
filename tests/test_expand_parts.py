"""Part-range/list expansion into one record per part.

See PIPELINE.md "Part expansion" for the full rule. The key
distinction: only an *explicit* range ("1 đến 10", "1-10" in a
part note, "từ 1 đến 10") or an explicit list ("các phần 1, 2,
5, 6, 7") expands. Hierarchical parts such as "4-41" in
TCVN 7447-4-41:2010 or "1-1" in EN 1994-1-1:2004 -- and a bare
hyphen code such as "BS EN 13146-1-10" on its own, which is
indistinguishable from one -- must NOT expand: the user's own
foreign-standards file contains EN 1993-1-10, EN 1991-1-2 and
IEC 60146-1-3, all single hierarchical documents.
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


def test_parser_does_not_mark_hierarchical_or_bare_parts():
    hierarchical = parse_standard_code("TCVN 7447-4-41:2010")
    assert hierarchical["std_parts"] == ["4", "41"]
    assert hierarchical["expanded_parts"] is None

    eurocode = parse_standard_code("EN 1994-1-1:2004/AC:2009")
    assert eurocode["std_parts"] == ["1", "1"]
    assert eurocode["expanded_parts"] is None

    # Bare hyphen form, with no range/list words: indistinguishable
    # from a hierarchical part, so it is deliberately NOT expanded.
    bare = parse_standard_code("BS EN 13146-1-10")
    assert bare["std_parts"] == ["1", "10"]
    assert bare["expanded_parts"] is None


def test_process_text_expands_user_range_example():
    records = process_text("BS EN 13146-1 đến 10:2019", use_ai_fallback=False)
    assert len(records) == 10
    # raw_text keeps the org as written (BS EN); corrected_code
    # uses the normalized org (EN), as in the rest of the pipeline.
    assert [r["raw_text"] for r in records] == [
        f"BS EN 13146-{n}:2019" for n in range(1, 11)
    ]
    assert [r["corrected_code"] for r in records] == [
        f"EN 13146-{n}:2019" for n in range(1, 11)
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


def test_process_text_does_not_expand_hierarchical_or_bare_codes():
    records = process_text("TCVN 7447-4-41:2010", use_ai_fallback=False)
    assert len(records) == 1
    assert records[0]["corrected_code"] == "TCVN 7447-4-41:2010"
    assert records[0]["parts"] == "4-41"

    records = process_text("BS EN 13146-1-10", use_ai_fallback=False)
    assert len(records) == 1
    assert records[0]["corrected_code"] == "EN 13146-1-10"


def test_process_candidate_stays_single_record_for_compatibility():
    record = process_candidate("BS EN 13146-1 đến 10:2019", use_ai_fallback=False)
    assert record["corrected_code"] == "EN 13146-1-10:2019"
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
