# Standard-code pipeline

`src/pipeline.py` ties the existing modules into one flow that matches
the spec in the task: ingest -> deterministic parse -> Gemini fallback
-> structured JSON.

## Flow

1. **Ingestion** — `src/ingestion/standard_code_extractor.py`
   - PDF via `pdfplumber` (page text + tables)
   - DOCX via `python-docx` (all paragraphs + table cells; this is the
     *generic* scanner, different from `src/parsers/word_table_parser.py`,
     which only understands tables with a fixed STT / title / code layout)
   - Excel via `pandas` (every cell, every sheet)
   - Candidates are deduplicated; scanned PDFs with no extractable text
     are skipped (OCR is out of scope).

2. **Deterministic parsing** — `src/parsers/std_code_parser.py`
   - Weights: org 0.2, main number 0.3, year 0.3, parts 0.1, suffix 0.1.
   - Org confidence multiplies the org weight: exact map match 1.0,
     heuristic 0.7, fallback 0.4. So `TCVN 1234:2020` scores exactly
     0.8, while a heuristic org with main + year only scores 0.74.
   - `confidence_score >= 0.8` (and main + year present) =>
     `verified=True`, no Gemini call.

3. **Gemini fallback** — `src/ai/gemini_standard_normalizer.py`
   - Triggered only for score < 0.8 or a parse failure, and only when
     the caller enables it (`use_ai_fallback=True`).
   - Gemini is asked, from its knowledge of real standards designations,
     for the most plausible correction plus a `reason`/`explanation`.
     It is **not** a live catalogue lookup, so the result always stays
     `verified=False`.
   - If Gemini is unconfigured or fails, the pipeline keeps the
     deterministic result, `verified=False`, and records the failure
     in `explanation` instead of crashing.
   - Configure with `.env` (see `.env.example`):
     `GEMINI_API_KEY`, `GEMINI_MODEL` (default `gemini-3.8-flash`).

4. **JSON output** — one object per distinct code:

```json
[
  {
    "raw_text": "TCVN 1234:2020",
    "corrected_code": "TCVN 1234:2020",
    "organization": "TCVN",
    "main_number": "1234",
    "year": 2020,
    "parts": null,
    "suffix": null,
    "confidence_score": 0.8,
    "verified": true,
    "explanation": "Deterministic parse passed (confidence >= 0.8); no AI correction applied."
  }
]
```

Field notes: `year` is an integer (or `null`); `parts` is a
dash-joined string such as `"1-1"` (or `null`); `corrected_code` is
the canonical `ORG MAIN[-PARTS]:YEAR[/SUFFIX]` rebuild for parsed
codes, and the Gemini suggestion itself when that suggestion cannot
be re-parsed. `confidence_score` is always a plain float so the
output is JSON-serialisable (the parser internally uses `Decimal`).

## Usage

```bash
pip install -r requirements.txt
PYTHONPATH=src python -m pipeline sample.docx
PYTHONPATH=src python -m pipeline sample.pdf sample.xlsx --use-ai-fallback -o out.json
PYTHONPATH=src python -m pipeline --text "See TCVN 1234:2020." --use-ai-fallback
```

Python API:

```python
from pipeline import process_document, process_candidate, process_text

records = process_document("sample.docx", use_ai_fallback=True)
records = process_candidate("ASTM D1234:2020", use_ai_fallback=True)
records = process_text("TCVN 1234:2020", use_ai_fallback=False)
```

## Tests

```bash
PYTHONPATH=src python -m pytest tests/ -q
```

`tests/test_pipeline.py` injects a fake Gemini suggester, so no API
key or network call is needed to test the fallback path.
