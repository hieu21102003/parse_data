# Standards_AI — Parser mã tiêu chuẩn

Công cụ trích xuất và chuẩn hoá **mã tiêu chuẩn / quy chuẩn** (TCVN, QCVN, ISO,
EN, BS, IEC, ASTM, JIS, GB, …) từ văn bản, PDF, DOCX và Excel. Kết quả là các
bản ghi có cấu trúc (JSON) kèm điểm tin cậy, hoặc file Excel 8 cột.

Dự án gồm 3 phần đang hoạt động:

1. **Pipeline + CLI** (`src/pipeline.py`) — chạy offline trên file/text.
2. **HTTP API** (`src/app/main.py`) — FastAPI, cho service khác gọi.
3. **Web UI** (`frontend/`) — giao diện tiếng Việt, gọi API same-origin.

---

## TL;DR cho AI agent / contributor

```bash
# Cài đặt
python -m venv .venv && .venv\Scripts\activate     # Windows
# source .venv/bin/activate                        # Linux/macOS
pip install -r requirements.txt

# Chạy toàn bộ test (188 test)
python -m pytest tests/ -q -o pythonpath=src

# CLI
PYTHONPATH=src python -m pipeline --text "TCVN 1234:2020"
PYTHONPATH=src python -m pipeline file.pdf -o ket_qua.xlsx

# API + UI
uvicorn src.app.main:app --host 0.0.0.0 --port 8000
# Swagger: http://localhost:8000/docs
```

Quy tắc bất di bất dịch khi sửa code:

- **Đọc `docs/PIPELINE.md` trước** khi động vào parser/ingestion — nó ghi lại
  toàn bộ quy tắc nghiệp vụ và lý do các quyết định (nhiều rule là để chống
  regression đã từng xảy ra).
- **Luôn chạy lại test** sau khi sửa. Mỗi file test tương ứng một nhóm bug thực
  tế; đừng "dọn" test cho khớp code nếu code đang sai.
- **Không commit `.env`**, không hardcode API key.
- Nếu `git status` báo gần như mọi file modified với số dòng `+` bằng `−`, đó
  là do line endings CRLF/LF, không phải thay đổi thật.

---

## Trạng thái hiện tại

| Thành phần | Trạng thái |
|---|---|
| Trích xuất mã từ PDF/DOCX/XLSX | ✅ Hoạt động |
| Parser deterministic + confidence | ✅ Hoạt động (188 test) |
| Gemini fallback (tuỳ chọn) | ✅ Hoạt động, luôn `verified=false` |
| Xuất JSON / Excel | ✅ Hoạt động |
| CLI | ✅ Hoạt động |
| HTTP API + Swagger | ✅ Hoạt động (`/api/v1/*`) |
| Web UI | ✅ Hoạt động |
| ORM/SQLAlchemy models cho PostgreSQL | 🟡 Có code, **pipeline/API chưa ghi DB** |
| RAG / vector store / chatbot | ❌ **Chưa có** (README cũ mô tả phần này; không tồn tại trong `src/`) |
| OCR PDF scan | ❌ Ngoài scope; PDF không có text bị bỏ qua |

---

## Kiến trúc & luồng dữ liệu

```text
PDF / DOCX / XLSX / plain text
        │
        ▼
src/ingestion/standard_code_extractor.py
  • regex tìm candidate code
  • quét từng cell/paragraph/page
  • gán hierarchy (parent_level_1/2), stt, standard_name
        │
        ▼
src/parsers/std_code_parser.py
  • tách org / main / parts / year / suffix / equivalent
  • chấm confidence: org 0.2 + main 0.3 + year 0.3 + parts 0.1 + suffix 0.1
  • verified = có main + year + score >= 0.8
        │  score < 0.8 hoặc parse fail
        ▼
src/ai/gemini_standard_normalizer.py   (tuỳ chọn, mặc định CLI bật / API tắt)
  • gọi Gemini, trả suggested_code + reason
  • KHÔNG BAO GIỜ set verified=true
        │
        ▼
src/pipeline.py
  • process_candidate / process_text / process_document
  • expand range/list thành 1 record/phần (trừ bare hyphen)
  • dedupe theo code
        │
        ├──▶ JSON (stdout hoặc .json)
        ├──▶ src/exporter/excel_exporter.py  → .xlsx 8 cột
        └──▶ src/app/main.py (FastAPI) → frontend/ hoặc service khác
```

---

## Cấu trúc thư mục

```text
parse_data/
├─ src/
│  ├─ pipeline.py                     # Entry point CLI + Python API (QUAN TRỌNG)
│  ├─ ingestion/
│  │  └─ standard_code_extractor.py   # PDF/DOCX/Excel/text → candidate records
│  ├─ parsers/
│  │  ├─ std_code_parser.py           # Parser deterministic (QUAN TRỌNG)
│  │  ├─ word_table_parser.py         # Parser bảng DOCX cố định (legacy, xem dưới)
│  │  ├─ std_code_parser_202603.py    # Legacy snapshot
│  │  ├─ std_code_parser_sai.py       # Legacy/thử nghiệm
│  │  ├─ std_code_parser - old.py     # Legacy
│  │  └─ test_*.py                    # Script chạy tay, KHÔNG phải pytest
│  ├─ ai/
│  │  └─ gemini_standard_normalizer.py  # Gemini fallback
│  ├─ exporter/
│  │  └─ excel_exporter.py            # Excel 8 cột
│  ├─ app/
│  │  └─ main.py                      # FastAPI app (QUAN TRỌNG)
│  └─ db/                             # SQLAlchemy models + session (chưa dùng ở runtime)
│     ├─ models.py                    # Nguồn schema chính
│     ├─ base.py, session.py, init_db.py
│     ├─ orm.py                       # Automap (import path chưa chuẩn, xem Gotchas)
│     ├─ schema/create_db.sql         # Tham khảo
│     └─ seed/seed_data.sql           # Tham khảo
├─ frontend/                          # UI tĩnh, không build step
│  ├─ index.html
│  └─ static/{app.css,app.js}
├─ tests/                             # 16 file, 188 test (pytest)
├─ docs/
│  ├─ PIPELINE.md                     # Đặc tả nghiệp vụ chi tiết (ĐỌC TRƯỚC)
│  ├─ API.md                          # Hướng dẫn gọi API + Docker
│  ├─ FRONTEND.md, GEMINI_PARSER.md
│  ├─ DEV_SETUP.md, SETUP_DATABASE.md
│  └─ Git Setup Guide for Standards_AI.md
├─ main.py                            # Script mẫu PyCharm (legacy)
├─ check_gemini_models.py             # Utility liệt kê model Gemini khả dụng
├─ bck/models.py                      # Backup model cũ
├─ requirements.txt                   # Full deps (gồm cả RAG không dùng)
├─ requirements-api.txt               # Deps tối thiểu cho API/Docker
├─ pyproject.toml
├─ Dockerfile / .dockerignore
├─ .env.example
└─ README.md
```

---

## Cài đặt & chạy

Yêu cầu: Python 3.12+ (khai báo trong `pyproject.toml` là `>=3.14`, nhưng code
chỉ dùng cú pháp 3.10+; Docker dùng 3.12 và test hiện chạy trên 3.13).

```bash
# Windows
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# Linux/macOS
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Tạo `.env` từ `.env.example` (không bắt buộc nếu chỉ parse offline; cần khi
dùng Gemini hoặc DB). `load_dotenv()` được gọi trong `src/ai/`, `src/app/` và
`src/db/session.py`.

---

## CLI

```bash
PYTHONPATH=src python -m pipeline sample.pdf
PYTHONPATH=src python -m pipeline sample.docx sample.xlsx -o out.json
PYTHONPATH=src python -m pipeline --text "TCVN 13695-1 đến 10:2023"
PYTHONPATH=src python -m pipeline --text "TCVN 1234:2020" -o ket_qua.xlsx
PYTHONPATH=src python -m pipeline sample.pdf --no-ai-fallback -o out.json
```

- `-o` đuôi `.json` → JSON; đuôi khác → Excel. Không có `-o` → JSON ra stdout.
- Gemini **bật mặc định** ở CLI; `--no-ai-fallback` để chạy offline hoàn toàn.
- `--use-ai-fallback` giữ cho tương thích, hiện là no-op.
- Không truyền `/tmp/...` trên Windows (đó là root ổ đĩa); dùng
  `ket_qua.xlsx` hoặc `output\ket_qua.xlsx`.

Python API:

```python
from pipeline import process_candidate, process_text, process_document

process_candidate("ASTM D4719-07")                  # 1 record, không expand
process_text("TCVN 13566-1,2,3:2022")               # list, expand thành 3 record
process_document("catalog.xlsx", use_ai_fallback=False)
```

---

## HTTP API

Chạy:

```bash
uvicorn src.app.main:app --host 0.0.0.0 --port 8000
```

| Method | Path | Mô tả |
|---|---|---|
| GET | `/api/v1/health` | `status`, `version`, `ai_available` |
| POST | `/api/v1/parse/code` | Parse 1 mã → 1 record (không expand) |
| POST | `/api/v1/parse/text` | Parse text → list (expand range/list) |
| POST | `/api/v1/parse/files` | Upload nhiều PDF/DOCX/XLSX/XLS/XLSM |

- Path cũ `/api/parse/text`, `/api/parse/files`, `/api/health` vẫn hoạt động
  (frontend dùng) nhưng ẩn khỏi Swagger.
- Auth tuỳ chọn: đặt `PARSER_API_KEY` → bắt buộc header `X-API-Key`.
- CORS: `CORS_ORIGINS` (mặc định `*`).
- Upload: tối đa 25 MB/file (`PARSER_MAX_UPLOAD_MB`).
- Pipeline sync được chạy qua `run_in_threadpool`, không block event loop.
- Chi tiết + ví dụ curl/Python/JS: **`docs/API.md`**.

---

## Output

### JSON (mỗi record)

```json
{
  "raw_text": "TCVN 1234:2020",
  "corrected_code": "TCVN 1234:2020",
  "standard_name": null,
  "parent_level_1": null,
  "parent_level_2": null,
  "stt": null,
  "organization": "TCVN",
  "main_number": "1234",
  "year": 2020,
  "parts": null,
  "suffix": null,
  "confidence_score": 0.8,
  "verified": true,
  "explanation": "Deterministic parse passed (confidence >= 0.8); no AI correction applied."
}
```

- `year`: int hoặc `null`; `parts`: chuỗi nối bằng `-` (vd `"1-10"`) hoặc `null`.
- `confidence_score`: float (0.0–1.0), luôn serialize được.
- `verified=true` chỉ khi parse deterministic có main + year + score ≥ 0.8.
  Kết quả Gemini luôn `verified=false`.
- `raw_text` được bảo đảm **chỉ là một mã đã làm sạch**, không bao giờ là cả
  dòng/cell/đoạn văn.
- API file trả thêm `source_file`; endpoint files trả thêm `files[]`.

### Excel — đúng 8 cột, đúng thứ tự

```text
Raw Text | Corrected Code | Standard Name | Organization | Main Number | Year | Parts | Suffix
```

- Header nền navy `000080`, chữ trắng đậm, canh giữa.
- 3 cột text canh trái (Raw Text, Corrected Code, Standard Name), 5 cột còn lại canh giữa.
- Width tự tính từ nội dung, cap 80.
- **Không** xuất `confidence_score`, `explanation`, `parent_level_*`, `stt`.
- Ghi binary bằng `workbook.save()`, không bao giờ `write_text()`.

---

## Quy tắc nghiệp vụ quan trọng (invariants)

Chi tiết đầy đủ ở `docs/PIPELINE.md`. Tóm tắt những chỗ dễ làm hỏng:

1. **Confidence & verified**
   - `org 0.2 × org_confidence` + `main 0.3` + `year 0.3` + `parts 0.1` + `suffix 0.1`.
   - `org_confidence`: exact map 1.0, heuristic 0.7, fallback 0.4.
   - `verified` yêu cầu **main + year + score ≥ 0.8**. Không có year → tối đa 0.7.
   - Gemini không bao giờ được set `verified=true`.

2. **Không expand bare hyphen**
   - `EN 1993-1-10` = Part 1, Chapter 10 → **một** document, parts `"1-10"`.
   - Chỉ expand khi có range/list rõ ràng: `-1 đến 10`, `từ 1 đến 10`,
     `(các phần 1-6)`, `1,2,3,4,5`.
   - Giới hạn: tối đa 100 phần, số phần ≤ 999; vượt → giữ record gốc.

3. **Equivalent code trong ngoặc**
   - `TCVN 13695-1 đến 10:2023 (BS EN 13146-1 đến 10:2019)` là **hai** code.
   - Mỗi code giữ year riêng; không lấy số của code trong ngoặc làm parts/year
     của code ngoài.
   - `BS EN` / `TCVN EN` được giữ nguyên, không rút gọn thành `EN`/`TCVN`.

4. **Year**
   - Hợp lệ trong khoảng 1900–2100. Token 4 số không hợp lệ ở vị trí year
     (vd `:1231`) bị bỏ, không biến thành suffix `/:1231`.
   - Year có thể nằm trong ngoặc nếu bên ngoài không có; year bên ngoài thắng.
   - Short year (`-07` → 2007) chỉ cho ASTM/AASHTO/GBJ.

5. **raw_text sạch**
   - Table quét từng cell, không join row.
   - `clean_code_candidate` loại prose bị regex nuốt; suffix multi-word bị bỏ.
   - Dedupe theo code (không phân biệt hoa/thường); extractor ưu tiên record có
     `row` (table) hơn match từ page text.

6. **Hierarchy**
   - `parent_level_1`: heading La Mã (`I. Nhóm …`).
   - `parent_level_2`: subsection dotted (`I.2.1. …`) hoặc `2. Thiết kế`.
   - Level-1 mới reset level-2; Excel reset theo từng sheet; DOCX/PDF giữ context
     theo thứ tự tài liệu.
   - Row có code không bao giờ bị coi là heading.

7. **standard_name**
   - Ưu tiên cột title/name trong header bảng; nếu không có, chọn text dài nhất
     có nghĩa trong row.
   - Title dạng `Phần 1: … Phần 2: …` được tách: mỗi part record chỉ nhận title
     của phần mình.

---

## Parser hỗ trợ những dạng nào

Xem `src/parsers/std_code_parser.py` (docstring đầu file) và
`tests/test_pipeline_real_world.py`:

- Year tuỳ chọn: `EN 50129`, `IEC 60529`, `TCVN 4756`
- Year bằng `-`, `/`, `:` hoặc space: `GB 50157-2003`, `EN 1337-1/2011`
- Part + year: `EN 50122-1-2011`, `DIN EN 13230-1-2009`
- Không space: `IEC62278:2002`, `IEC60044-1`
- Series letter: `JIS E 1102`, `ASTM C 665`, `JISC1731-2`
- Decimal main: `IEEE 802.11`, `ASME B1.20.7`
- Short year: `ASTM D 4719-07` → 2007, `AASHTO T27-99` → 1999
- Comma list: `TCVN 13566-1,2,3,4,5:2022`
- Range tiếng Việt: `từ 1 đến 10`, `-1 đến 10`, `phần 1 đến 3`
- Equivalent trong ngoặc (kể cả thiếu dấu đóng)

Thêm org mới: cập nhật **cả hai** nơi —
`ORG_MAP` trong `src/parsers/std_code_parser.py` và `_STANDARD_CODE_CORE`
trong `src/ingestion/standard_code_extractor.py` — rồi thêm test.

---

## Ingestion

`extract_standard_codes(file_path, use_ai_fallback=False)` dispatch theo đuôi:

- `.pdf` → `pdfplumber`: page text + tables. Không OCR.
- `.docx` → `python-docx`: duyệt body theo đúng thứ tự paragraph/table.
- `.xlsx/.xls/.xlsm` → `pandas.read_excel(sheet_name=None)`.

`process_document` cố ý gọi ingestion với `use_ai_fallback=False`, sau đó mới
gọi Gemini trong `process_candidate` → **mỗi candidate chưa verified chỉ gọi
Gemini một lần**, không gọi theo số lần xuất hiện.

---

## Gemini fallback

- File: `src/ai/gemini_standard_normalizer.py`.
- REST API trực tiếp bằng `urllib` (không dùng SDK).
- Env: `GEMINI_API_KEY`, `GEMINI_MODEL` (mặc định `gemini-3.5-flash`).
- Response schema cố định: `suggested_code, alternatives, status, confidence, reason`.
- Lỗi cấu hình (`GeminiConfigurationError`) và lỗi request (`GeminiRequestError`)
  được bắt riêng; pipeline giữ kết quả deterministic và ghi lỗi vào
  `explanation`, **không crash**.
- Kết quả AI chỉ là gợi ý, không tra cứu catalogue thật → luôn `verified=false`.

---

## Database (chuẩn bị, chưa nối runtime)

- PostgreSQL qua SQLAlchemy 2.0. Schema định nghĩa tại `src/db/models.py`
  (organizations, standards, standard_identifiers, standard_equivalents,
  standard_aliases, standard_documents, standard_versions, categories,
  standard_categories, category_standard_listing, legal_documents,
  legal_standard_references).
- `src/db/session.py` build URL từ `DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD`
  — **không dùng** `DATABASE_URL` dù biến này có trong `.env.example`.
- Tạo bảng: `python src/db/init_db.py` (import `src.db` → load models vào metadata).
- `schema/create_db.sql` và `seed/seed_data.sql` chỉ để tham khảo; `models.py` là
  nguồn sự thật.
- Pipeline và API hiện **không** đọc/ghi DB. Nếu cần lưu kết quả, viết thêm lớp
  repository/service, đừng nhét vào parser.

---

## Testing

```bash
python -m pytest tests/ -q -o pythonpath=src
# hoặc: PYTHONPATH=src python -m pytest tests/ -q
```

- 16 file, **188 test**. Không cần API key/network: Gemini được inject/fake
  trong test.
- `-o pythonpath=src` cần thiết vì một số test import top-level `parsers.*`,
  `pipeline`, `exporter.*`.
- Nhóm test tiêu biểu:
  - `test_pipeline.py` — contract pipeline + Gemini giả.
  - `test_std_code_parser.py` — parser thuần.
  - `test_pipeline_real_world.py` — mã thực tế từ file Excel.
  - `test_expand_parts.py`, `test_compound_equivalent.py` — expand/equiv.
  - `test_hierarchy_context.py` — heading + stt.
  - `test_raw_text_clean.py` — raw_text không bị lẫn prose.
  - `test_excel_exporter.py` — đúng 8 cột, style, CLI output.
  - `test_app_api.py` — API contract, auth, upload.

---

## Cấu hình (`.env`)

| Biến | Mặc định | Dùng ở |
|---|---|---|
| `GEMINI_API_KEY` | (trống) | Gemini fallback |
| `GEMINI_MODEL` | `gemini-3.5-flash` | Gemini fallback |
| `PARSER_API_KEY` | (trống = API mở) | FastAPI auth |
| `CORS_ORIGINS` | `*` | FastAPI CORS |
| `PARSER_MAX_UPLOAD_MB` | `25` | FastAPI upload |
| `DB_HOST` / `DB_PORT` | `localhost` / `5432` | `src/db/session.py` |
| `DB_NAME` | `standards_ai` | `src/db/session.py` |
| `DB_USER` / `DB_PASSWORD` | `postgres` / `postgres` | `src/db/session.py` |

---

## Docker

```bash
docker build -t standards-parser .
docker run --rm -p 8000:8000 --env-file .env standards-parser
```

- Image dùng `requirements-api.txt` (không kéo langchain/faiss/unstructured).
- Chỉ copy `src/` + `frontend/`; không copy `.env`, tests, docs, dữ liệu.
- Public internet: bật `PARSER_API_KEY` và đặt sau reverse proxy HTTPS.

---

## Legacy / dead code — đừng sửa nhầm

Các file sau **không** thuộc đường chạy chính:

- `src/parsers/std_code_parser - old.py`, `std_code_parser_202603.py`,
  `std_code_parser_sai.py` — snapshot/thử nghiệm cũ.
- `src/parsers/word_table_parser.py` + `word_table_parser - v1.py` — parser bảng
  DOCX layout cố định (STT/title/code), chỉ dùng bởi script tay
  `src/parsers/test_*.py`. Pipeline dùng `ingestion/standard_code_extractor.py`.
- `src/parsers/test_*.py` — script chạy tay, **không** phải pytest.
- `main.py` (root) — script mẫu PyCharm.
- `bck/models.py` — backup model.
- `check_gemini_models.py` — utility liệt kê model Gemini.

> README cũ từng mô tả kiến trúc RAG/chatbot. Đó là định hướng, không phải code
> hiện có. Đừng tạo `src/rag/`, `src/vector_store/` trừ khi được yêu cầu.

---

## Gotchas đã biết

- `src/db/orm.py` import `from db.session` (thiếu `src.`) → chỉ chạy khi `src/`
  nằm trên `PYTHONPATH`; import dạng `src.db.orm` sẽ lỗi. Không dùng file này
  trong runtime.
- `pyproject.toml` khai báo `requires-python >= 3.14` nhưng Docker/venv thực tế
  dùng 3.12/3.13. Code không dùng tính năng riêng của 3.14.
- `requirements.txt` chứa langchain/faiss/unstructured **không được import**;
  dùng `requirements-api.txt` cho môi trường gọn.
- Excel xuất 8 cột (có `Standard Name`); đừng quay lại 7 cột — test và docs đã
  đồng bộ theo 8.
- Frontend hiển thị thêm `status` (từ `verified`) và không hiển thị `suffix`.
- API mặc định **tắt** Gemini (`use_ai_fallback=false`), CLI mặc định **bật**.

---

## Muốn sửa gì thì vào đâu

| Nhu cầu | File |
|---|---|
| Regex nhận diện mã / thêm org | `src/ingestion/standard_code_extractor.py` (`_STANDARD_CODE_CORE`) + `ORG_MAP` |
| Quy tắc year/parts/suffix | `src/parsers/std_code_parser.py` (`_parse_remainder`) |
| Confidence / verified | `src/parsers/std_code_parser.py` (`compute_confidence`) |
| Expand range/list | `_expanded_parts_for` (parser) + `_expand_record` (`src/pipeline.py`) |
| Field JSON output | `OUTPUT_FIELDS` + `_record_from_parsed` (`src/pipeline.py`) |
| Cột Excel | `COLUMNS` (`src/exporter/excel_exporter.py`) + `tests/test_excel_exporter.py` |
| Endpoint / auth / CORS | `src/app/main.py`, `docs/API.md` |
| UI | `frontend/index.html`, `frontend/static/app.js`, `app.css` |
| Prompt/model Gemini | `src/ai/gemini_standard_normalizer.py` |
| Schema DB | `src/db/models.py` |

---

## Tài liệu

- `docs/PIPELINE.md` — đặc tả pipeline & toàn bộ rule (chi tiết nhất).
- `docs/API.md` — gọi API, auth, curl/Python/JS, Docker.
- `docs/FRONTEND.md` — endpoint UI dùng.
- `docs/GEMINI_PARSER.md` — hành vi parser + Gemini.
- `docs/DEV_SETUP.md` — setup môi trường.
- `docs/SETUP_DATABASE.md` — PostgreSQL.

---

## License

Nội bộ / Private project.
