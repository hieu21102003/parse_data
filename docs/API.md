# Gọi parser như một API

API được dựng bằng FastAPI trong `src/app/main.py`, dùng lại trực tiếp
`src/pipeline.py` (không có logic parse riêng trong tầng HTTP).

## Chạy server

```bash
# trong .venv đã cài dependencies
uvicorn src.app.main:app --host 0.0.0.0 --port 8000
```

- Swagger UI: <http://127.0.0.1:8000/docs>
- OpenAPI JSON: <http://127.0.0.1:8000/openapi.json>
- `--host 0.0.0.0` để máy/service khác trong LAN gọi được (nhớ mở firewall port 8000).

Chạy bằng Docker:

```bash
docker build -t standards-parser .
docker run --rm -p 8000:8000 --env-file .env standards-parser
```

## Xác thực (tuỳ chọn)

Mặc định API mở. Đặt biến môi trường để bắt buộc header:

```env
PARSER_API_KEY=mot-chuoi-bi-mat
```

Khi đó mọi endpoint parse yêu cầu:

```
X-API-Key: mot-chuoi-bi-mat
```

Sai/thiếu key trả `401`. `/api/v1/health` và `/docs` luôn mở.

## Endpoints

| Method | Path | Mô tả |
|---|---|---|
| GET | `/api/v1/health` | Health + version + `ai_available` |
| POST | `/api/v1/parse/code` | Parse 1 mã, trả 1 record (không expand range) |
| POST | `/api/v1/parse/text` | Parse toàn bộ text, expand range/list thành từng phần |
| POST | `/api/v1/parse/files` | Upload nhiều file PDF/DOCX/XLSX/XLS/XLSM |

Các path cũ `/api/parse/text`, `/api/parse/files`, `/api/health` vẫn hoạt
động (frontend đang dùng) nhưng bị ẩn khỏi Swagger. Nên dùng `/api/v1/*`
cho tích hợp mới.

### `POST /api/v1/parse/code`

```bash
curl -s http://localhost:8000/api/v1/parse/code \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: mot-chuoi-bi-mat' \
  -d '{"code": "TCVN 13566-1,2,3:2022", "use_ai_fallback": false}'
```

```json
{
  "raw_text": "TCVN 13566-1,2,3:2022",
  "corrected_code": "TCVN 13566-1-2-3:2022",
  "standard_name": null,
  "parent_level_1": null,
  "parent_level_2": null,
  "stt": null,
  "organization": "TCVN",
  "main_number": "13566",
  "year": 2022,
  "parts": "1-2-3",
  "suffix": null,
  "confidence_score": 0.9,
  "verified": true,
  "explanation": "Deterministic parse passed (confidence >= 0.8); no AI correction applied.",
  "source_file": null
}
```

`/parse/code` cố ý **không** expand `1,2,3` thành 3 record — dùng
`/parse/text` nếu cần expand.

### `POST /api/v1/parse/text`

```bash
curl -s http://localhost:8000/api/v1/parse/text \
  -H 'Content-Type: application/json' \
  -d '{"text": "TCVN 13566-1,2,3:2022 và ISO 9001:2015", "use_ai_fallback": false}'
```

```json
{ "records": [ ... ], "count": 4 }
```

### `POST /api/v1/parse/files`

```bash
curl -s http://localhost:8000/api/v1/parse/files \
  -F 'files=@danh_muc.pdf' \
  -F 'files=@tieu_chuan.xlsx' \
  -F 'use_ai_fallback=false'
```

```json
{
  "records": [ { "raw_text": "...", "source_file": "danh_muc.pdf", "...": "..." } ],
  "count": 42,
  "files": [ { "filename": "danh_muc.pdf", "count": 30 },
             { "filename": "tieu_chuan.xlsx", "count": 12 } ]
}
```

Giới hạn mỗi file 25 MB (đổi bằng `PARSER_MAX_UPLOAD_MB`). File được ghi
ra temp, xử lý xong thì xoá; API không lưu file/kết quả vào DB.

## Ví dụ từ service khác

Python (`requests`):

```python
import requests

BASE = "http://parser.internal:8000"
headers = {"X-API-Key": "mot-chuoi-bi-mat"}

resp = requests.post(
    f"{BASE}/api/v1/parse/text",
    json={"text": "TCVN 13695-1 đến 10:2023 (BS EN 13146-1 đến 10:2019)"},
    headers=headers,
    timeout=60,
)
resp.raise_for_status()
for record in resp.json()["records"]:
    print(record["corrected_code"], record["verified"])
```

JavaScript (browser, cần CORS):

```js
const res = await fetch("http://localhost:8000/api/v1/parse/text", {
  method: "POST",
  headers: { "Content-Type": "application/json", "X-API-Key": "mot-chuoi-bi-mat" },
  body: JSON.stringify({ text: "ISO 9001:2015", use_ai_fallback: false }),
});
const data = await res.json();
```

Cấu hình CORS khi gọi từ browser ở origin khác:

```env
CORS_ORIGINS=https://app.example.com,https://admin.example.com
```

Mặc định `CORS_ORIGINS=*` (không kèm cookie/credentials).

## Mã lỗi

| Status | Khi nào |
|---|---|
| 401 | Thiếu/sai `X-API-Key` khi `PARSER_API_KEY` được đặt |
| 413 | File vượt `PARSER_MAX_UPLOAD_MB` |
| 415 | Đuôi file không hỗ trợ |
| 422 | Body rỗng/không hợp lệ, hoặc không đọc được file |
| 500 | Lỗi không lường trước (không nên xảy ra: pipeline tự bắt lỗi Gemini) |

## Ghi chú thiết kế

- Endpoint `async` nhưng pipeline là sync/CPU-bound, nên được chạy qua
  `run_in_threadpool` để không chặn event loop khi nhiều request cùng lúc.
- Response model Pydantic (`ParseRecord`) giữ `extra="allow"`, nên field
  mới thêm vào pipeline vẫn được trả ra mà không phá contract.
- `verified=true` chỉ khi parse deterministic đạt confidence ≥ 0.8 và có
  main number + year. Kết quả Gemini luôn `verified=false` và có
  `explanation` để đối chiếu.
- Gemini mặc định **tắt** ở API (`use_ai_fallback: false`); bật khi cần,
  yêu cầu `GEMINI_API_KEY` trong `.env`.
