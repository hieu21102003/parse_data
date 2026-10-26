# Gemini fallback for malformed standard codes

The regular parser remains deterministic and does not make network requests. Gemini is an optional fallback for codes that the regular parser cannot parse.

## Configure

Copy `.env.example` to `.env`, then set:

```env
GEMINI_API_KEY=your_key_from_google_ai_studio
GEMINI_MODEL=gemini-3.8-flash
```

Keep `.env` private. The Gemini request sends the supplied code string to Google's API. The code uses Python's standard HTTP client, so no additional Gemini SDK is required.

## Parse one code

```python
from src.parsers.std_code_parser import parse_standard_code_with_ai_fallback

result = parse_standard_code_with_ai_fallback("garbled or inconsistently formatted code")
print(result)
```

Gemini is called only if the normal parser fails. The result adds an `ai_fallback` object containing the suggestion, alternatives, explanation, and model confidence. `verified` is always `false`: this feature suggests a likely interpretation, but does not check an official standards catalogue.

## Parse codes from a Word file

```python
from src.parsers.word_table_parser import parse_word_tables

records = parse_word_tables("path/to/standards.docx", use_ai_fallback=True)
```

The existing Word parser reads standard-code cells from DOCX tables and sends an individual code to Gemini only when deterministic parsing fails. It does not upload the Word file itself. Leave `use_ai_fallback=False` (the default) to keep parsing offline.

Gemini uses the `generateContent` REST endpoint with JSON structured output. Change `GEMINI_MODEL` if the model configured for your API key differs.

## Extract codes from PDF and Excel

The generic extractor scans all page text and detected table rows in a text-based PDF, or every cell across all sheets in `.xlsx`, `.xls`, and `.xlsm` workbooks. It searches for known standards-body prefixes, removes duplicate codes, and returns the code plus its first source location. Codes can be embedded among unrelated rows or columns.

```python
from src.ingestion.standard_code_extractor import extract_standard_codes

results = extract_standard_codes("path/to/catalog.pdf")
# or: results = extract_standard_codes("path/to/catalog.xlsx")
for item in results:
    print(item["code"], item.get("page"), item.get("sheet"), item.get("row"))
```

Set `use_ai_fallback=True` to let Gemini interpret candidate codes the regular parser cannot parse. This can help with irregular formatting, but the candidate finder still relies on recognized organization prefixes. The extractor does not confirm that a suggested code exists in an official catalogue. PDF pages without extractable text are skipped; OCR is outside this feature.
