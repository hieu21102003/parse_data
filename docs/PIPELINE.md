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
   - Year is optional in the parser (it was previously required after
     a colon, which made most real-world codes score 0.0). Year may
     come after `:`, `-`, `/`, or a space, and parts are hyphen
     groups that are not a year. Supported real-world forms include
     no-space org-number (`IEC62278:2002`), series letters
     (`JIS E 1102`, `ASTM C 665`, `JISC1731-2`), decimal mains
     (`IEEE 802.11`, `ASME B1.20.7`), and short edition years only
     for ASTM/AASHTO/GBJ (`ASTM D 4719-07` -> 2007, `AASHTO T27-99`
     -> 1999). For other bodies a trailing 2-digit group is a part
     (`JIS B8009-12`, `EN 301489-18`), not a year.
   - A code with no year in the source can score at most 0.7, so it
     stays unverified with `year: null` and an explanation saying
     the year is missing in the source. That is not a parser failure:
     filling the year needs Gemini research or the source document.
   - A parenthetical part note is not discarded: `TCVN 13566:2022
     (các phần 1-6)` gives `parts: "1-6"`, `TCVN 1234:2020 (phần 1
     đến 3)` gives `parts: "1-3"`, while `(rev 1)` stays version
     text only and does not become a part.
   - Vietnamese ranges: `từ X đến Y` ("from X to Y") and `-X đến Y`
     (leading hyphen = range start) are full ranges, not single
     parts: `TCVN 13566 (từ 1 đến 10, 2019)` gives `parts: "1-10"`
     and `year: 2019`, and `TCVN 13566 từ 1 đến 10:2019` gives the
     same. A 4-digit year inside the parentheses is the publication
     year when no year appears outside them (it is not dropped to
     `null`); an outside year, when present, wins.

3. **Gemini fallback** — `src/ai/gemini_standard_normalizer.py`
   - Triggered for score < 0.8 or a parse failure, and enabled by
     default: `process_candidate` / `process_document` /
     `process_text` call `suggest_standard_code(raw_text)` directly
     unless the caller passes `use_ai_fallback=False` (CLI:
     `--no-ai-fallback`). `--use-ai-fallback` is kept for
     compatibility and is now a no-op (the default is already on).
   - Gemini is asked, from its knowledge of real standards designations,
     for the most plausible correction plus a `reason`/`explanation`.
     It is **not** a live catalogue lookup, so the result always stays
     `verified=False`.
   - If Gemini is unconfigured (`GeminiConfigurationError`, e.g. no
     `GEMINI_API_KEY`) or the request fails (`GeminiRequestError`,
     e.g. network/API error), the pipeline keeps the deterministic
     result, `verified=False`, and records a clear, distinct error
     in `explanation` instead of crashing.
   - The Gemini prompt also tells the model to treat Vietnamese
     parenthetical part notes (`các phần 1-6`, `phần 1 đến 3`) as a
     part range, not a version, and to state the range in
     `reason`/`explanation`. It now also covers `từ X đến Y` /
     `-X đến Y` (both endpoints, e.g. `1-10`, never just `1`) and a
     year inside the parentheses (e.g. `(từ 1 đến 10, 2019)` ->
     year 2019, stated as taken from the parenthetical note). The
     JSON `OUTPUT_SCHEMA` is unchanged (same fields, same required
     list).
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
PYTHONPATH=src python -m pipeline sample.pdf sample.xlsx -o out.json
PYTHONPATH=src python -m pipeline --text "See TCVN 1234:2020."
PYTHONPATH=src python -m pipeline sample.pdf --no-ai-fallback -o out.json
```

Python API:

```python
from pipeline import process_document, process_candidate, process_text

records = process_document("sample.docx")  # Gemini fallback on by default
records = process_candidate("ASTM D1234:2020")
records = process_text("TCVN 1234:2020", use_ai_fallback=False)  # offline only
```

## Tests

```bash
PYTHONPATH=src python -m pytest tests/ -q
```

`tests/test_pipeline.py` injects a fake Gemini suggester, so no API
key or network call is needed to test the fallback path.
