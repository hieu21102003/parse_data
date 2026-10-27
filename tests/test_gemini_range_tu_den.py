"""Tests for 'từ X đến Y' / '-X đến Y' part ranges and parenthetical years.

Run from the repo root, as the existing tests do:
    PYTHONPATH=src python -m pytest tests/test_gemini_range_tu_den.py -q

No live Gemini call is made: the prompt test mocks urlopen and only
checks what prompt would be sent.
"""

import json

try:
    from parsers.std_code_parser import parse_standard_code
except ModuleNotFoundError:  # pragma: no cover - repo-root PYTHONPATH
    from src.parsers.std_code_parser import parse_standard_code  # type: ignore

try:
    from ai import gemini_standard_normalizer as gemini
except ModuleNotFoundError:  # pragma: no cover - repo-root PYTHONPATH
    from src.ai import gemini_standard_normalizer as gemini  # type: ignore

try:
    from pipeline import process_candidate, process_text
except ModuleNotFoundError:  # pragma: no cover - repo-root PYTHONPATH
    from src.pipeline import process_candidate, process_text  # type: ignore


def test_tu_den_range_with_parenthetical_year():
    parsed = parse_standard_code("TCVN 13566 (từ 1 đến 10, 2019)")
    assert parsed["std_parts"] == ["1", "10"]
    assert parsed["std_year"] == 2019
    assert parsed["verified"] is True
    record = process_candidate("TCVN 13566 (từ 1 đến 10, 2019)")
    assert record["parts"] == "1-10"
    assert record["year"] == 2019
    assert record["corrected_code"] == "TCVN 13566-1-10:2019"


def test_leading_hyphen_range_with_parenthetical_year():
    parsed = parse_standard_code("TCVN 13566 (-1 đến 10, 2019)")
    assert parsed["std_parts"] == ["1", "10"]
    assert parsed["std_year"] == 2019


def test_cac_phan_tu_den_range_with_year():
    parsed = parse_standard_code("TCVN 13566 (các phần từ 1 đến 10, 2019)")
    assert parsed["std_parts"] == ["1", "10"]
    assert parsed["std_year"] == 2019


def test_range_outside_parentheses():
    parsed = parse_standard_code("TCVN 13566 từ 1 đến 10:2019")
    assert parsed["std_parts"] == ["1", "10"]
    assert parsed["std_year"] == 2019
    parsed = parse_standard_code("TCVN 13566-1 đến 10:2019")
    assert parsed["std_parts"] == ["1", "10"]
    assert parsed["std_year"] == 2019


def test_parenthetical_year_only_and_outside_year_wins():
    parsed = parse_standard_code("TCVN 13566 (2019)")
    assert parsed["std_parts"] == []
    assert parsed["std_year"] == 2019
    parsed = parse_standard_code("TCVN 13566:2020 (2019)")
    assert parsed["std_year"] == 2020


def test_process_text_keeps_tu_den_range_and_year():
    # Part expansion: a "từ 1 đến 10" range now yields one record
    # per part, each keeping the year; the single "1-10" record
    # is still what process_candidate returns.
    records = process_text("Áp dụng TCVN 13566 từ 1 đến 10:2019.")
    assert [r["corrected_code"] for r in records] == [
        f"TCVN 13566-{n}:2019" for n in range(1, 11)
    ]
    assert all(r["year"] == 2019 for r in records)
    records = process_text("Áp dụng TCVN 13566 (từ 1 đến 10, 2019).")
    assert len(records) == 10
    assert records[0]["parts"] == "1"
    assert all(r["year"] == 2019 for r in records)


def test_process_text_does_not_capture_sentence_date_range():
    records = process_text("Áp dụng TCVN 1234:2020 đến 2025.")
    assert len(records) == 1
    assert records[0]["raw_text"] == "TCVN 1234:2020"
    assert records[0]["year"] == 2020
    assert records[0]["parts"] is None


def test_gemini_prompt_covers_tu_den_and_parenthetical_year(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            suggestion = {
                "suggested_code": "TCVN 13566-1-10:2019",
                "alternatives": [],
                "status": "normalized",
                "confidence": 0.9,
                "reason": "Range tu 1 den 10, year 2019 taken from parenthetical note.",
            }
            payload = {"candidates": [{"content": {"parts": [{"text": json.dumps(suggestion)}]}}]}
            return json.dumps(payload).encode("utf-8")

    def fake_urlopen(request, timeout=None):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr(gemini, "urlopen", fake_urlopen)
    suggestion = gemini.suggest_standard_code("TCVN 13566 (từ 1 đến 10, 2019)")
    prompt = captured["body"]["contents"][0]["parts"][0]["text"]
    assert "từ 1 đến 10" in prompt
    assert "-1 đến 10" in prompt
    assert "1-10" in prompt
    assert "year 2019 taken from parenthetical note" in prompt
    assert "TCVN 13566-1-10:2019" in prompt
    # Schema sent with the request is unchanged.
    assert captured["body"]["generationConfig"]["responseSchema"] == gemini.OUTPUT_SCHEMA
    assert gemini.OUTPUT_SCHEMA["required"] == [
        "suggested_code", "alternatives", "status", "confidence", "reason",
    ]
    assert suggestion["verified"] is False
