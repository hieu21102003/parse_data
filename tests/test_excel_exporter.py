"""Tests for the Excel exporter (src/exporter/excel_exporter.py)
and the pipeline CLI --output handling.

Run from the repo root, as the existing tests do:
    PYTHONPATH=src python -m pytest tests/test_excel_exporter.py -q
"""

import json

from openpyxl import load_workbook

try:
    from exporter.excel_exporter import COLUMNS, export_to_excel
except ModuleNotFoundError:  # pragma: no cover - repo-root PYTHONPATH
    from src.exporter.excel_exporter import COLUMNS, export_to_excel  # type: ignore

try:
    from pipeline import main
except ModuleNotFoundError:  # pragma: no cover - repo-root PYTHONPATH
    from src.pipeline import main  # type: ignore

EXPECTED_HEADERS = [
    "Raw Text", "Corrected Code", "Organization", "Main Number",
    "Year", "Parts", "Suffix",
]

RECORDS = [
    {
        "raw_text": "TCVN 13695-1 đến 10:2023",
        "corrected_code": "TCVN 13695-1-10:2023",
        "organization": "TCVN",
        "main_number": "13695",
        "year": 2023,
        "parts": "1-10",
        "suffix": None,
        # Extra JSON fields must NOT become Excel columns.
        "confidence_score": 0.9,
        "verified": True,
        "explanation": "Deterministic parse passed.",
    },
    {
        "raw_text": "TCVN 4756",
        "corrected_code": "TCVN 4756",
        "organization": "TCVN",
        "main_number": "4756",
        "year": None,
        "parts": None,
        "suffix": "AC:2009",
        "confidence_score": 0.5,
        "verified": False,
        "explanation": "Year missing.",
    },
]


def test_columns_are_exactly_seven_in_order():
    assert [header for header, _, _ in COLUMNS] == EXPECTED_HEADERS
    assert len(COLUMNS) == 7


def test_export_writes_only_seven_columns_in_order(tmp_path):
    path = tmp_path / "ket_qua.xlsx"
    returned = export_to_excel(RECORDS, path)
    assert str(returned) == str(path)

    workbook = load_workbook(path)
    sheet = workbook.active
    assert sheet.max_column == 7
    assert sheet.max_row == 3
    assert [cell.value for cell in sheet[1]] == EXPECTED_HEADERS
    assert [cell.value for cell in sheet[2]] == [
        "TCVN 13695-1 đến 10:2023", "TCVN 13695-1-10:2023", "TCVN",
        "13695", 2023, "1-10", None,
    ]
    assert [cell.value for cell in sheet[3]] == [
        "TCVN 4756", "TCVN 4756", "TCVN", "4756", None, None, "AC:2009",
    ]
    # No confidence_score / explanation anywhere in the sheet.
    values = [cell.value for row in sheet.iter_rows() for cell in row]
    assert 0.9 not in values
    assert "Deterministic parse passed." not in values


def test_header_style_is_navy_white_bold_centered(tmp_path):
    path = tmp_path / "styled.xlsx"
    export_to_excel(RECORDS, path)
    sheet = load_workbook(path).active
    for cell in sheet[1]:
        assert cell.fill.fgColor.rgb.endswith("000080")  # navy
        assert cell.font.color.rgb.endswith("FFFFFF")  # white
        assert cell.font.bold is True
        assert cell.alignment.horizontal == "center"


def test_data_alignments(tmp_path):
    path = tmp_path / "aligned.xlsx"
    export_to_excel(RECORDS, path)
    sheet = load_workbook(path).active
    row = sheet[2]
    # Raw Text and Corrected Code: left; the other five: center.
    assert row[0].alignment.horizontal == "left"
    assert row[1].alignment.horizontal == "left"
    for cell in row[2:]:
        assert cell.alignment.horizontal == "center"


def test_column_widths_follow_content_length(tmp_path):
    path = tmp_path / "widths.xlsx"
    export_to_excel(RECORDS, path)
    sheet = load_workbook(path).active
    # Corrected Code is the longest corrected value (20 chars) -> 22.
    assert sheet.column_dimensions["B"].width == len("TCVN 13695-1-10:2023") + 2
    # Year column: header "Year" (4) beats any year value -> 6.
    assert sheet.column_dimensions["E"].width == 6
    assert sheet.column_dimensions["A"].width > len("Raw Text")


def test_export_empty_records_still_writes_header(tmp_path):
    path = tmp_path / "empty.xlsx"
    export_to_excel([], path)
    sheet = load_workbook(path).active
    assert sheet.max_column == 7
    assert sheet.max_row == 1
    assert [cell.value for cell in sheet[1]] == EXPECTED_HEADERS


def test_cli_output_xlsx_writes_excel_and_confirms(tmp_path, capsys):
    path = tmp_path / "ket_qua.xlsx"
    assert main(["--text", "TCVN 1234:2020", "-o", str(path)]) == 0
    assert "Excel file successfully created:" in capsys.readouterr().out
    assert path.exists()
    sheet = load_workbook(path).active
    assert [cell.value for cell in sheet[1]] == EXPECTED_HEADERS
    assert [cell.value for cell in sheet[2]] == [
        "TCVN 1234:2020", "TCVN 1234:2020", "TCVN", "1234", 2020, None, None,
    ]


def test_cli_output_json_still_writes_json(tmp_path, capsys):
    path = tmp_path / "out.json"
    assert main(["--text", "TCVN 1234:2020", "-o", str(path)]) == 0
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload[0]["corrected_code"] == "TCVN 1234:2020"
    # JSON output keeps the full JSON record, including confidence.
    assert payload[0]["confidence_score"] == 0.8
