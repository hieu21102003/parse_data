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
   - `raw_text` keeps the matched code and recognized short notes (parts,
     year, version, or equivalent code). Descriptive parentheticals are
     excluded from the code text; codes inside them are extracted separately.
   - When a row's title is a part list (base title plus
     `Phần 1: …`, `Phần 2: …`, …), each single-part record gets
     only the base title plus its own part's title
     (`standard_name_for_parts`); records with no part, a part
     range, or a part not listed in the title keep the full title.
   - **Part expansion** — a code whose parts come from an explicit
     range or list is expanded into one record per part, in
     `process_text` and `process_document` (and via the new
     `process_candidate_expanded`; `process_candidate` itself
     still returns the single range record for compatibility):
     `BS EN 13146-1 đến 10:2019` → `BS EN 13146-1:2019` …
     `BS EN 13146-10:2019` (raw_text keeps `BS EN` as written,
     corrected_code normalises it to `EN`); `EN 13481 (các phần
     1, 2, 5, 6, 7)` → exactly `EN 13481-1, -2, -5, -6, -7`, with
     no invented parts and no invented year; a comma list written
     after the first part, `TCVN 13566-1,2,3,4,5:2022` → exactly
     `TCVN 13566-1:2022` … `TCVN 13566-5:2022`, year kept on every
     part. A complete code is org + main + part + year + optional
     equivalent; a missing field is simply left out, never
     invented. Year and suffix are kept on every expanded part,
     a part-list title is re-split per expanded part, and a part
     that appears both inside a range/list and on its own is
     emitted only once. The parser marks this with `parts_kind`
     (`"range"` / `"list"`) and `expanded_parts`; expansion is
     capped at 100 parts and at part numbers ≤ 999, so a misread
     date range or an oversized range keeps its single record.
   - **Bare hyphen codes do NOT expand** — a code written
     `ORG MAIN-A-B` with no range/list words is Part A,
     Chapter B, a single document, not a range: `EN 1993-1-10`
     is Part 1, Chapter 10, and `TCVN 7447-4-41:2010` is
     Part 4, Chapter 41, so each keeps its single record with
     parts `"1-10"` / `"4-41"`. An earlier version (PR #11)
     expanded bare hyphen codes as ranges; that was wrong
     under the standard's numbering and was reverted. To
     expand, write the range or list explicitly (`…-1 đến 10`,
     `…-1,2,3,4,5`, or `(các phần 1, 2, …)`). What also does
     NOT expand: a single part, and a degenerate `1-1`
     (e.g. `EN 1994-1-1:2004`).
   - `raw_text` is guaranteed to be exactly one cleaned matched code,
     never a whole row, paragraph or cell string: tables are scanned
     cell by cell (never joined with `" | "`), the extractor emits
     only `clean_code_candidate(match)` as `"code"`, `process_document`
     never falls back to a `raw_text` field, and `process_candidate` /
     `_record_from_parsed` re-extract the first cleaned code from any
     input that contains one (see `extract_first_clean_code`).
     A trailing `/<word>` that is not a real suffix (e.g. `/ Ti` from
     `/ Tiêu chuẩn…`) is stripped in the extractor, and a multi-word
     suffix in the parser is dropped instead of becoming
     `corrected_code`. Only when no code matches at all is the
     stripped input kept, so a malformed candidate stays visible.

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
     A digit token in the year position that is not a valid year
     (1900-2100), e.g. `:1231` or `/9999`, counts the same way:
     it is neither a year nor a suffix and is dropped, so the
     canonical code never gains an invented `/:1231` suffix.
   - A parenthetical part note is not discarded: `TCVN 13566:2022
     (các phần 1-6)` gives `parts: "1-6"`, `TCVN 1234:2020 (phần 1
     đến 3)` gives `parts: "1-3"`, while `(rev 1)` stays version
     text only and does not become a part.
   - Vietnamese ranges: `từ X đến Y` ("from X to Y") and `-X đến Y`
     (leading hyphen = range start) are full ranges, not single
     parts: `TCVN 13566 (từ 1 đến 10, 2019)` gives `parts: "1-10"`
     and `year: 2019`, and `TCVN 13566 từ 1 đến 10:2019` gives the
     same. The part keyword may sit on either side of such a
     range -- `(từ phần 1 đến 10)`, `(từ 1 đến phần 10)`,
     `(từ phần 1 đến phần 10)` -- and the separator may be a
     hyphen (`từ 1 - 10`); all are the same range. A 4-digit year inside the parentheses is the publication
     year when no year appears outside them (it is not dropped to
     `null`); an outside year, when present, wins.
   - Compound code with an equivalent in parentheses:
     `TCVN 13695-1 đến 10:2023 (BS EN 13146-1 đến 10:2019)` is
     TWO codes, not one. Text/document runs emit both records:
     `TCVN 13695-1-10:2023` and `EN 13146-1-10:2019` (BS EN
     normalises to EN), each with its own range and year. The
     hyphen-part plus `đến` rule applies per code (`-1 đến 10`
     -> `1-10`, never `1` alone), the equivalent's numbers are
     never stolen as the outer code's parts/year, and an unclosed
     trailing parenthesis is handled the same way. A single
     `process_candidate` call on the whole string keeps the outer
     code correct and names the equivalent in `explanation`.
   - A space before/after the hyphen does not change the code:
     `ISO 3452 -1 đến 6` is ISO 3452, parts `1-6`. Detection:
     a parenthetical is an equivalent code when it starts with
     an organisation + main number (it is emitted as its own
     records and expanded the same way as the outer code);
     a parenthetical with no organisation + main number, e.g.
     `(các phần từ 1 - 6)`, is a part note for the outer code
     only and produces no extra record.

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
     year 2019, stated as taken from the parenthetical note), and
     compound equivalents (`TCVN 13695-1 đến 10:2023 (BS EN
     13146-1 đến 10:2019)` -> main code `TCVN 13695-1-10:2023`,
     equivalent `BS EN 13146-1-10:2019` in `alternatives` and in
     `reason`/`explanation`, each code keeping its own year). The
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
    "standard_name": null,
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

## Excel output

```bash
PYTHONPATH=src python -m pipeline --text "TCVN 1234:2020" -o ket_qua.xlsx
```

`-o` / `--output` with a `.xlsx` path (or any non-`.json` path)
writes a formatted Excel file via `src/exporter/excel_exporter.py`
(using `openpyxl`) instead of JSON, and prints
`Excel file successfully created: <path>`. With a `.json` path it
still writes JSON, as before; with no `-o` it prints JSON to stdout.

Output paths:
- A plain relative name (`-o ket_qua.xlsx`) is written straight
  into the current directory where the command was run. There is
  no hardcoded `/tmp` path anywhere: on Windows do NOT copy a
  `/tmp/ket_qua.xlsx` example as `\tmp\ket_qua.xlsx` -- that is
  the root of the current drive, not the current directory, and
  may not exist or may not be writable. Use `ket_qua.xlsx` or
  `output\ket_qua.xlsx` instead.
- A path with a directory (`-o output/ket_qua.xlsx`) has its
  parent directory created first
  (`Path(args.output).parent.mkdir(parents=True, exist_ok=True)`
  in `pipeline.py`, and the same in the exporter), so it no
  longer fails with FileNotFoundError just because the folder
  is new. This applies to both Excel and JSON output.
- Excel is written as binary only (`workbook.save()`), never
  with `write_text()`: a `.xlsx` file is a ZIP archive, and
  writing it as text corrupts it. JSON output, being text,
  correctly keeps `write_text()`.

The Excel file has exactly eight columns, in this order, and no
others (in particular no `confidence_score` or `explanation`):

`Raw Text | Corrected Code | Standard Name | Organization | Main Number | Year | Parts | Suffix`

Header: navy fill (`000080`), white bold text, centered. Data:
left-aligned for Raw Text and Corrected Code, centered for the
other five columns. Column widths are set from the content length
(longest header/cell + 2, capped at 80). Empty fields (`year`,
`parts`, `suffix` when missing) become blank cells, not the text
`None`.

## Tests

```bash
PYTHONPATH=src python -m pytest tests/ -q
```

`tests/test_pipeline.py` injects a fake Gemini suggester, so no API
key or network call is needed to test the fallback path.
