"""Tests for Vietnamese part-range parentheticals and the Gemini prompt.

Run from the repo root, as the existing tests do:
    PYTHONPATH=src python -m pytest tests/test_gemini_part_range.py -q

No live Gemini call is made: the prompt test mocks urlopen and only
checks what prompt would be sent, and the parser tests are deterministic.
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


def test_part_range_cac_phan():
    parsed = parse_standard_code("TCVN 13566:2022 (các phần 1-6)")
    assert parsed["std_main_number"] == "13566"
    assert parsed["std_year"] == 2022
    assert parsed["std_parts"] == ["1", "6"]
    assert parsed["version_text"] == "các phần 1-6"
    assert parsed["verified"] is True

    record = process_candidate("TCVN 13566:2022 (các phần 1-6)")
    assert record["parts"] == "1-6"
    assert record["corrected_code"] == "TCVN 13566-1-6:2022"


def test_part_range_phan_den():
    parsed = parse_standard_code("TCVN 1234:2020 (phần 1 đến 3)")
    assert parsed["std_parts"] == ["1", "3"]
    assert parsed["std_year"] == 2020


def test_part_list_cac_phan():
    parsed = parse_standard_code("TCVN 1234:2020 (các phần 1, 3, 5)")
    assert parsed["std_parts"] == ["1", "3", "5"]


def test_version_note_is_not_a_part():
    parsed = parse_standard_code("TCVN 1234:2020 (rev 1)")
    assert parsed["std_parts"] == []
    assert parsed["version_text"] == "rev 1"


def test_process_text_keeps_parenthetical_part_range():
    # End-to-end via --text / document extraction: the extractor must
    # not strip "(các phần 1-6)" before the parser sees it.
    records = process_text("Áp dụng TCVN 13566:2022 (các phần 1-6).")
    assert len(records) == 1
    assert records[0]["raw_text"] == "TCVN 13566:2022 (các phần 1-6)"
    assert records[0]["parts"] == "1-6"


def test_code_parts_win_over_parenthetical():
    parsed = parse_standard_code("EN 1991-1-1:2002 (các phần 1-6)")
    assert parsed["std_parts"] == ["1", "1"]


def test_output_schema_fields_unchanged():
    assert set(gemini.OUTPUT_SCHEMA["properties"].keys()) == {
        "suggested_code", "alternatives", "status", "confidence", "reason", "explanation",
    }
    assert gemini.OUTPUT_SCHEMA["required"] == [
        "suggested_code", "alternatives", "status", "confidence", "reason",
    ]
    assert gemini.OUTPUT_SCHEMA["properties"]["status"]["enum"] == [
        "normalized", "ambiguous", "unrecognized",
    ]


def test_gemini_prompt_covers_part_range(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            suggestion = {
                "suggested_code": "TCVN 13566-1-6:2022",
                "alternatives": [],
                "status": "normalized",
                "confidence": 0.9,
                "reason": "Parenthetical note is a part range 1-6, not a version.",
            }
            payload = {"candidates": [{"content": {"parts": [{"text": json.dumps(suggestion)}]}}]}
            return json.dumps(payload).encode("utf-8")

    def fake_urlopen(request, timeout=None):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr(gemini, "urlopen", fake_urlopen)
    suggestion = gemini.suggest_standard_code("TCVN 13566:2022 (các phần 1-6)")
    prompt = captured["body"]["contents"][0]["parts"][0]["text"]
    assert "các phần 1-6" in prompt
    assert "phần 1 đến 3" in prompt
    assert "PART RANGE" in prompt
    assert "no extra fields" in prompt
    # The schema sent with the request is the unchanged OUTPUT_SCHEMA.
    assert captured["body"]["generationConfig"]["responseSchema"] == gemini.OUTPUT_SCHEMA
    assert suggestion["verified"] is False
    assert suggestion["explanation"] == suggestion["reason"]
