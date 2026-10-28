# Web interface

The FastAPI app serves the parser UI at `/` and exposes the pipeline through
two same-origin endpoints:

- `POST /api/parse/text` accepts JSON `{ "text": "...", "use_ai_fallback": false }`.
- `POST /api/parse/files` accepts multipart `files` fields and an optional
  `use_ai_fallback` field. Supported files are PDF, DOCX, XLSX, XLS and XLSM.
- `GET /api/health` returns a small health response.

File results include `standard_name` when the source table has a title/name
column or the title can be inferred from other cells in that row. Plain text
input has `standard_name: null` because it has no file row to associate.
The UI table displays hierarchy context columns (`stt`, `parent_level_1`,
and `parent_level_2`) alongside standard names, parsed codes, and metadata.

Start from the repository root after installing `requirements.txt`:

```bash
python -m uvicorn src.app.main:app --reload
```

Open <http://127.0.0.1:8000>. Gemini suggestions are optional and disabled
by default in the UI. Enable the checkbox to use the existing Gemini fallback;
this requires `GEMINI_API_KEY` in `.env`. The parser does not perform OCR on
scanned PDFs. Uploads are processed from temporary files and removed after
each request; the web interface does not save documents or parse results to
the database.
