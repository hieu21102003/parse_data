"""Tests: split a part-list standard_name to match each record's part.

Run from the repo root with src/ on the path, as the existing tests do:
    PYTHONPATH=src python -m pytest tests/test_standard_name_parts.py -q

A title cell can hold a whole part list, e.g.::

    Cầu đường sắt khổ 1435, tốc độ đến 350 km/h
    - Phần 1: Quy định chung, Phần 2: Thiết kế tổng thể, ...

Previously every part record (TCVN 13594-1, -2, -3, ...) got that
entire list as its standard_name. Now a record with exactly one
part gets only the shared base title plus its own part's title.
Every case that cannot be matched safely keeps the full title, so
splitting never loses information.
"""

try:
    from ingestion.standard_code_extractor import standard_name_for_parts
    from pipeline import process_document
except ModuleNotFoundError:  # pragma: no cover - repo-root PYTHONPATH
    from src.ingestion.standard_code_extractor import (  # type: ignore
        standard_name_for_parts,
    )
    from src.pipeline import process_document  # type: ignore

TITLE = (
    "Cầu đường sắt khổ 1435, tốc độ đến 350 km/h"
    " - Phần 1: Quy định chung"
    ", Phần 2: Thiết kế tổng thể và tải trọng tác động"
    ", Phần 3: Tải trọng tác động"
    ", Phần 4: Phân tích kết cấu"
    ", Phần 10: Cầu chịu tác động của động đất"
)
BASE = "Cầu đường sắt khổ 1435, tốc độ đến 350 km/h"


def _parsed(parts):
    return {"std_parts": parts}


def test_each_part_gets_only_its_own_title():
    assert standard_name_for_parts(TITLE, _parsed(["1"])) == (
        BASE + " - Phần 1: Quy định chung"
    )
    assert standard_name_for_parts(TITLE, _parsed(["2"])) == (
        BASE + " - Phần 2: Thiết kế tổng thể và tải trọng tác động"
    )
    # "Phần 10" must not be mistaken for "Phần 1" plus a stray "0".
    assert standard_name_for_parts(TITLE, _parsed(["10"])) == (
        BASE + " - Phần 10: Cầu chịu tác động của động đất"
    )
    for name in (
        standard_name_for_parts(TITLE, _parsed(["1"])),
        standard_name_for_parts(TITLE, _parsed(["2"])),
    ):
        assert "Phần 3" not in name and "Phần 4" not in name


def test_no_part_range_or_unlisted_part_keeps_full_title():
    # No part: the record covers the whole standard.
    assert standard_name_for_parts(TITLE, _parsed([])) == TITLE
    # A range covers several parts, so no single part title applies.
    assert standard_name_for_parts(TITLE, _parsed(["1", "10"])) == TITLE
    # A part not listed in the title: fall back, do not invent one.
    assert standard_name_for_parts(TITLE, _parsed(["11"])) == TITLE


def test_non_part_list_title_and_english_part_list():
    plain = "Bê tông cốt thép - Yêu cầu chung"
    assert standard_name_for_parts(plain, _parsed(["1"])) == plain
    english = "Railway bridges - Part 1: General, Part 2: Design loads"
    assert standard_name_for_parts(english, _parsed(["2"])) == (
        "Railway bridges - Part 2: Design loads"
    )


def test_excel_rows_get_matching_part_titles(tmp_path):
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["STT", "Tên tiêu chuẩn", "Mã tiêu chuẩn"])
    for index, code in enumerate(
        ["TCVN 13594-1:2022", "TCVN 13594-2:2022", "TCVN 13594-3:2022"],
        start=1,
    ):
        sheet.append([index, TITLE, code])
    path = tmp_path / "parts.xlsx"
    workbook.save(str(path))
    records = process_document(str(path), use_ai_fallback=False)
    assert [r["corrected_code"] for r in records] == [
        "TCVN 13594-1:2022",
        "TCVN 13594-2:2022",
        "TCVN 13594-3:2022",
    ]
    assert records[0]["standard_name"] == BASE + " - Phần 1: Quy định chung"
    assert records[1]["standard_name"] == (
        BASE + " - Phần 2: Thiết kế tổng thể và tải trọng tác động"
    )
    assert records[2]["standard_name"] == BASE + " - Phần 3: Tải trọng tác động"
