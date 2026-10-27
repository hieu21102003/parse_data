"""Regression tests: raw_text must contain only the matched standard code.

Run from the repo root with src/ on the path, as the existing tests do:
    PYTHONPATH=src python -m pytest tests/test_raw_text_clean.py -q

The bug: when a table row, paragraph or cell contained a long
description around a code (e.g. "TCVN 13594-1:2022"), the output
record's raw_text -- and, through the corrected_code fallback, even
corrected_code -- could carry the whole surrounding text. The fix
guarantees, at every result-creation point, that raw_text is exactly
one cleaned matched code, never a row/paragraph/cell string.
"""

try:
    from ingestion.standard_code_extractor import (
        _extract_from_text,
        extract_first_clean_code,
    )
    from parsers.std_code_parser import parse_standard_code
    from pipeline import process_candidate, process_document, process_text
except ModuleNotFoundError:  # pragma: no cover - repo-root PYTHONPATH
    from src.ingestion.standard_code_extractor import (  # type: ignore
        _extract_from_text,
        extract_first_clean_code,
    )
    from src.parsers.std_code_parser import parse_standard_code  # type: ignore
    from src.pipeline import (  # type: ignore
        process_candidate,
        process_document,
        process_text,
    )

CODE = "TCVN 13594-1:2022"
DESC = (
    "Tiêu chuẩn về bê tông cốt thép dùng cho kết cấu chịu lực "
    "trong công trình dân dụng và công nghiệp"
)


def test_process_candidate_row_string_returns_only_code():
    # The reported root cause: a whole joined row passed to the
    # pipeline used to become raw_text (and corrected_code) verbatim.
    record = process_candidate(f"1 | {CODE} | {DESC}", use_ai_fallback=False)
    assert record["raw_text"] == CODE
    assert record["corrected_code"] == CODE
    assert record["verified"] is True
    assert record["suffix"] is None


def test_process_candidate_description_before_and_after_code():
    record = process_candidate(f"{DESC} {CODE} áp dụng rộng rãi.", use_ai_fallback=False)
    assert record["raw_text"] == CODE
    assert record["corrected_code"] == CODE


def test_process_candidate_dash_description_is_not_a_suffix():
    record = process_candidate(f"{CODE} - {DESC}", use_ai_fallback=False)
    assert record["raw_text"] == CODE
    assert record["corrected_code"] == CODE
    assert record["suffix"] is None


def test_process_candidate_descriptive_parenthetical_is_stripped():
    record = process_candidate(f"{CODE} (quy định chung về bê tông)", use_ai_fallback=False)
    assert record["raw_text"] == CODE
    assert record["corrected_code"] == CODE


def test_process_candidate_keeps_part_range_parenthetical():
    # Guard against over-stripping: a part-range note is part of the
    # code, not a description, so it must survive cleaning.
    record = process_candidate(f"TCVN 13566:2022 (các phần 1-6)", use_ai_fallback=False)
    assert record["raw_text"] == "TCVN 13566:2022 (các phần 1-6)"
    assert record["parts"] == "1-6"


def test_process_candidate_without_any_code_match_is_kept_not_dropped():
    # No code match -> the stripped input is kept, so a malformed
    # candidate is still visible instead of silently disappearing.
    record = process_candidate("không có mã nào ở đây", use_ai_fallback=False)
    assert record["raw_text"] == "không có mã nào ở đây"
    assert record["verified"] is False
    record = process_candidate("XYZ 1234:2020", use_ai_fallback=False)
    assert record["raw_text"] == "XYZ 1234:2020"


def test_extract_first_clean_code():
    assert extract_first_clean_code(f"1 | {CODE} | {DESC}") == CODE
    assert extract_first_clean_code("không có mã nào ở đây") is None


def test_extractor_slash_description_is_not_a_suffix():
    records = _extract_from_text(f"{CODE} / Tiêu chuẩn về bê tông", {}, False)
    assert [r["code"] for r in records] == [CODE]
    assert records[0]["parsed"]["suffix"] is None


def test_extractor_real_slash_suffixes_are_kept():
    records = _extract_from_text("EN 1994-1-1:2004/AC:2009", {}, False)
    assert records[0]["code"] == "EN 1994-1-1:2004/AC:2009"
    assert records[0]["parsed"]["suffix"] == "AC:2009"
    records = _extract_from_text("QCVN 06:2022/BXD", {}, False)
    assert records[0]["code"] == "QCVN 06:2022/BXD"
    assert records[0]["parsed"]["suffix"] == "BXD"


def test_parser_multiword_suffix_prose_is_dropped():
    parsed = parse_standard_code(f"{CODE} | {DESC}")
    assert parsed["suffix"] is None
    parsed = parse_standard_code("EN 1994-1-1:2004/AC:2009")
    assert parsed["suffix"] == "AC:2009"


def test_process_text_row_string_yields_only_code():
    records = process_text(f"1 | {CODE} | {DESC}", use_ai_fallback=False)
    assert [r["raw_text"] for r in records] == [CODE]


def test_docx_table_row_raw_text_is_only_code(tmp_path):
    from docx import Document

    doc = Document()
    table = doc.add_table(rows=1, cols=3)
    for index, value in enumerate(["1", CODE, DESC]):
        table.rows[0].cells[index].text = value
    path = tmp_path / "table.docx"
    doc.save(str(path))
    records = process_document(str(path), use_ai_fallback=False)
    assert [r["raw_text"] for r in records] == [CODE]
    assert all(DESC not in r["raw_text"] for r in records)


def test_excel_table_row_raw_text_is_only_code(tmp_path):
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["STT", "Mã", "Tên tiêu chuẩn"])
    sheet.append(["1", CODE, DESC])
    path = tmp_path / "table.xlsx"
    workbook.save(str(path))
    records = process_document(str(path), use_ai_fallback=False)
    assert [r["raw_text"] for r in records] == [CODE]
    assert all(DESC not in r["raw_text"] for r in records)


def test_process_document_never_falls_back_to_raw_text_field(monkeypatch):
    # A record without a cleaned "code" field must be skipped, even
    # if it carries a "raw_text" field holding a whole row string.
    # That fallback is exactly how row text used to become raw_text.
    import pipeline as pipeline_module

    monkeypatch.setattr(
        pipeline_module,
        "extract_standard_codes",
        lambda path, use_ai_fallback=False: [
            {"raw_text": f"1 | {CODE} | {DESC}", "parsed": None}
        ],
    )
    assert process_document("dummy.xlsx", use_ai_fallback=False) == []
