"""Tests for the end-to-end pipeline in src/pipeline.py.

Run from the repo root with src/ on the path, as the existing tests do:
    PYTHONPATH=src python -m pytest tests/test_pipeline.py -q

Gemini is never called in these tests: low-confidence cases use an
injected fake suggester, and the failure case uses a raising suggester.
"""

import json

import pytest

try:
    from pipeline import OUTPUT_FIELDS, process_candidate, process_document, process_text
except ModuleNotFoundError:  # pragma: no cover - repo-root PYTHONPATH
    from src.pipeline import OUTPUT_FIELDS, process_candidate, process_document, process_text  # type: ignore


def test_output_schema_exact_fields():
    record = process_candidate("TCVN 1234:2020")
    assert set(record.keys()) == set(OUTPUT_FIELDS)
    assert record["raw_text"] == "TCVN 1234:2020"
    assert record["corrected_code"] == "TCVN 1234:2020"
    assert record["organization"] == "TCVN"
    assert record["main_number"] == "1234"
    assert record["year"] == 2020
    assert record["parts"] is None
    assert record["suffix"] is None
    assert isinstance(record["confidence_score"], float)
    assert isinstance(record["verified"], bool)


def test_verified_at_threshold():
    # org 0.2 + main 0.3 + year 0.3 = 0.8 exactly -> verified, no AI.
    record = process_candidate("TCVN 1234:2020", use_ai_fallback=True)
    assert record["confidence_score"] == 0.8
    assert record["verified"] is True


def test_verified_with_parts_and_suffix():
    record = process_candidate("EN 1994-1-1:2004/AC:2009")
    assert record["verified"] is True
    assert record["parts"] == "1-1"
    assert record["suffix"] == "AC:2009"
    assert record["corrected_code"] == "EN 1994-1-1:2004/AC:2009"


def test_low_confidence_without_ai_stays_unverified():
    # Heuristic org (QCVN is not in ORG_MAP, 0.7) -> 0.14 + 0.3 + 0.3 = 0.74 < 0.8.
    # Note: "ASTM D1234:2020" is a different case -- it fails the deterministic
    # regex entirely (0.0) because a letter is attached to the number.
    record = process_candidate("QCVN 1234:2020", use_ai_fallback=False)
    assert record["confidence_score"] == 0.74
    assert record["verified"] is False
    assert "AI fallback not enabled" in record["explanation"]


def test_low_confidence_with_fake_ai_correction():
    def fake_suggester(raw):
        return {
            "suggested_code": "QCVN 1234:2020",
            "status": "normalized",
            "confidence": 0.9,
            "reason": "Confirmed the QCVN designation and canonical spacing.",
            "explanation": "Confirmed the QCVN designation and canonical spacing.",
            "alternatives": [],
        }

    record = process_candidate(
        "QCVN 1234:2020", use_ai_fallback=True, ai_suggester=fake_suggester)
    assert record["verified"] is False  # AI results are never verified
    assert record["explanation"].startswith("Confirmed the QCVN")
    assert record["corrected_code"] == "QCVN 1234:2020"


def test_ai_failure_does_not_crash():
    def failing_suggester(raw):
        raise RuntimeError("no API key")

    record = process_candidate(
        "???", use_ai_fallback=True, ai_suggester=failing_suggester)
    assert record["verified"] is False
    assert "AI fallback failed" in record["explanation"]


def test_process_text_deduplicates():
    records = process_text("See TCVN 1234:2020 and again TCVN 1234:2020.")
    assert len(records) == 1
    assert records[0]["verified"] is True


def test_process_docx_and_xlsx(tmp_path):
    from docx import Document
    import pandas as pd

    docx_path = tmp_path / "sample.docx"
    doc = Document()
    doc.add_paragraph("Applicable: TCVN 1234:2020, and TCVN 7447-4-41:2010.")
    doc.save(str(docx_path))

    xlsx_path = tmp_path / "sample.xlsx"
    pd.DataFrame([["TCVN 1234:2020"], ["ISO 9001:2015"]]).to_excel(
        str(xlsx_path), index=False, header=False)

    docx_records = process_document(str(docx_path))
    assert {r["corrected_code"] for r in docx_records} == {
        "TCVN 1234:2020", "TCVN 7447-4-41:2010"}
    assert all(r["verified"] for r in docx_records)

    xlsx_records = process_document(str(xlsx_path))
    assert {r["corrected_code"] for r in xlsx_records} == {
        "TCVN 1234:2020", "ISO 9001:2015"}

    # Whole output must be JSON-serialisable with the exact schema.
    payload = json.dumps(docx_records + xlsx_records, ensure_ascii=False)
    assert json.loads(payload)[0]["raw_text"]
