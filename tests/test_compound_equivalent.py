"""Tests for a compound code with an equivalent in parentheses.

The user's exact failing string:
    TCVN 13695-1 đến 10:2023 (BS EN 13146-1 đến 10:2019
(with and without the closing parenthesis).

Before this fix, the closed form was consumed as a single candidate
so the BS EN code (and its year 2019) never became its own record,
and the hyphen-part plus "đến" range could be read as parts "1"
alone. No live Gemini call is made: the prompt test mocks urlopen.
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
    from pipeline import process_candidate, process_document, process_text
except ModuleNotFoundError:  # pragma: no cover - repo-root PYTHONPATH
    from src.pipeline import process_candidate, process_text, process_document  # type: ignore

CLOSED = "TCVN 13695-1 đến 10:2023 (BS EN 13146-1 đến 10:2019)"
UNCLOSED = "TCVN 13695-1 đến 10:2023 (BS EN 13146-1 đến 10:2019"


def test_parser_closed_compound_keeps_full_range_and_equivalent():
    parsed = parse_standard_code(CLOSED)
    assert parsed["std_parts"] == ["1", "10"]
    assert parsed["std_year"] == 2023
    assert parsed["suffix"] is None
    assert parsed["equivalent_text"] == "BS EN 13146-1 đến 10:2019"
    assert parsed["verified"] is True


def test_parser_unclosed_compound_keeps_full_range_and_no_suffix():
    parsed = parse_standard_code(UNCLOSED)
    assert parsed["std_parts"] == ["1", "10"]
    assert parsed["std_year"] == 2023
    assert parsed["suffix"] is None
    assert parsed["equivalent_text"] == "BS EN 13146-1 đến 10:2019"


def test_parser_does_not_steal_equivalent_numbers():
    # TCVN has no parts/year of its own here; BS EN's 13146-1 and
    # 2019 must NOT become TCVN's parts/year.
    parsed = parse_standard_code("TCVN 13695 (BS EN 13146-1 đến 10:2019)")
    assert parsed["std_parts"] == []
    assert parsed["std_year"] is None
    assert parsed["equivalent_text"] == "BS EN 13146-1 đến 10:2019"


def test_process_candidate_preserves_equivalent_in_explanation():
    record = process_candidate(CLOSED)
    assert record["parts"] == "1-10"
    assert record["year"] == 2023
    assert record["corrected_code"] == "TCVN 13695-1-10:2023"
    assert "BS EN 13146-1 đến 10:2019" in record["explanation"]


def test_process_text_yields_both_codes_with_both_years():
    for text in (CLOSED, UNCLOSED):
        records = process_text(text)
        by_code = {r["corrected_code"]: r for r in records}
        assert by_code["TCVN 13695-1-10:2023"]["parts"] == "1-10"
        assert by_code["TCVN 13695-1-10:2023"]["year"] == 2023
        # BS EN normalises to EN, as in the existing BS EN -> EN rule.
        assert by_code["EN 13146-1-10:2019"]["parts"] == "1-10"
        assert by_code["EN 13146-1-10:2019"]["year"] == 2019


def test_process_document_yields_both_codes(tmp_path):
    from docx import Document

    path = tmp_path / "compound.docx"
    doc = Document()
    doc.add_paragraph(f"Áp dụng {CLOSED}.")
    doc.save(str(path))

    records = process_document(str(path))
    codes = {r["corrected_code"]: r for r in records}
    assert codes["TCVN 13695-1-10:2023"]["year"] == 2023
    assert codes["EN 13146-1-10:2019"]["year"] == 2019
    assert codes["EN 13146-1-10:2019"]["parts"] == "1-10"


def test_gemini_prompt_covers_compound_equivalent(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            suggestion = {
                "suggested_code": "TCVN 13695-1-10:2023",
                "alternatives": ["BS EN 13146-1-10:2019"],
                "status": "normalized",
                "confidence": 0.9,
                "reason": "Equivalent in parentheses: BS EN 13146-1-10:2019, parts 1-10, year 2019; TCVN year is 2023, not 2019.",
            }
            payload = {"candidates": [{"content": {"parts": [{"text": json.dumps(suggestion)}]}}]}
            return json.dumps(payload).encode("utf-8")

    def fake_urlopen(request, timeout=None):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr(gemini, "urlopen", fake_urlopen)
    suggestion = gemini.suggest_standard_code(CLOSED)
    prompt = captured["body"]["contents"][0]["parts"][0]["text"]
    assert "TCVN 13695-1-10:2023" in prompt
    assert "BS EN 13146-1-10:2019" in prompt
    assert "Do NOT merge" in prompt
    assert "never return parts '1' alone" in prompt or "parts '1-10'" in prompt
    assert captured["body"]["generationConfig"]["responseSchema"] == gemini.OUTPUT_SCHEMA
    assert gemini.OUTPUT_SCHEMA["required"] == [
        "suggested_code", "alternatives", "status", "confidence", "reason",
    ]
    assert suggestion["alternatives"] == ["BS EN 13146-1-10:2019"]
    assert suggestion["verified"] is False
