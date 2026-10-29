"""FastAPI wrapper around the standard-code pipeline.

Run locally::

    uvicorn src.app.main:app --host 0.0.0.0 --port 8000

Interactive API docs: http://127.0.0.1:8000/docs

Stable contract for other services: ``/api/v1/*`` (see docs/API.md).
The legacy ``/api/parse/*`` paths and ``/api/health`` are kept as hidden
aliases so the bundled frontend and existing callers keep working.

Configuration (environment / .env):
  PARSER_API_KEY          optional shared secret; when set, every parse
                          endpoint requires the ``X-API-Key`` header.
  CORS_ORIGINS            comma-separated allowed browser origins
                          (default ``*``); only needed for browser callers.
  PARSER_MAX_UPLOAD_MB    per-file upload limit in MB (default 25).
"""

import hmac
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from dotenv import load_dotenv
from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from src.pipeline import process_candidate, process_document, process_text


load_dotenv()

ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / "frontend"
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".xls", ".xlsm"}


def _env_int(name: str, default: int) -> int:
    """Read a positive integer from the environment, falling back safely."""
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


MAX_UPLOAD_MB = _env_int("PARSER_MAX_UPLOAD_MB", 25)
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
# Read once at import: changing the key requires a restart (documented).
PARSER_API_KEY = os.getenv("PARSER_API_KEY", "").strip()


def _cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "*").strip()
    if not raw or raw == "*":
        return ["*"]
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


# -------------------------------------------------
# Response / request contract
# -------------------------------------------------
class ParseRecord(BaseModel):
    """One pipeline record; extra fields are preserved for compatibility."""

    model_config = ConfigDict(extra="allow")

    raw_text: str | None = None
    corrected_code: str | None = None
    standard_name: str | None = None
    parent_level_1: str | None = None
    parent_level_2: str | None = None
    stt: str | int | None = None
    organization: str | None = None
    main_number: str | None = None
    year: int | None = None
    parts: str | None = None
    suffix: str | None = None
    confidence_score: float = 0.0
    verified: bool = False
    explanation: str = ""
    source_file: str | None = None


class ParseResponse(BaseModel):
    records: list[ParseRecord]
    count: int


class FileResult(BaseModel):
    filename: str | None = None
    count: int


class FileParseResponse(ParseResponse):
    files: list[FileResult]


class HealthResponse(BaseModel):
    status: str
    version: str
    ai_available: bool


class TextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    use_ai_fallback: bool = False


class CodeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=1_000)
    use_ai_fallback: bool = False


# -------------------------------------------------
# Auth
# -------------------------------------------------
def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    """Enforce ``X-API-Key`` only when PARSER_API_KEY is configured."""
    if not PARSER_API_KEY:
        return
    if not x_api_key or not hmac.compare_digest(x_api_key, PARSER_API_KEY):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Send it in the X-API-Key header.",
            headers={"WWW-Authenticate": "X-API-Key"},
        )


# -------------------------------------------------
# App + routers
# -------------------------------------------------
app = FastAPI(
    title="Standards AI Parser",
    version="1.0.0",
    description=(
        "Extract and normalize standard codes (TCVN, QCVN, ISO, EN, BS, IEC, "
        "ASTM, ...) from plain text, PDF, DOCX and Excel files. "
        "Deterministic parsing with an optional Gemini fallback."
    ),
    openapi_tags=[
        {"name": "parse", "description": "Parse standard codes from text or documents."},
        {"name": "system", "description": "Health and readiness."},
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key"],
)

api = APIRouter(prefix="/api/v1", tags=["parse"], dependencies=[Depends(require_api_key)])
# Existing frontend calls /api/parse/*; keep those paths working but
# hide them from the OpenAPI schema.
legacy_api = APIRouter(
    prefix="/api",
    tags=["parse"],
    dependencies=[Depends(require_api_key)],
    include_in_schema=False,
)

app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/health", response_model=HealthResponse, tags=["system"], include_in_schema=False)
@app.get("/api/v1/health", response_model=HealthResponse, tags=["system"])
def health():
    return {
        "status": "ok",
        "version": app.version,
        "ai_available": bool(os.getenv("GEMINI_API_KEY", "").strip()),
    }


# -------------------------------------------------
# Endpoints
# -------------------------------------------------
@api.post("/parse/code", response_model=ParseRecord, summary="Parse one standard code")
@legacy_api.post("/parse/code", response_model=ParseRecord)
async def parse_code_endpoint(request: CodeRequest):
    """Parse a single code (no range/list expansion)."""
    code = request.code.strip()
    if not code:
        raise HTTPException(status_code=422, detail="Hãy nhập mã tiêu chuẩn.")
    # The pipeline is CPU-bound/synchronous: run it off the event loop.
    return await run_in_threadpool(
        process_candidate, code, use_ai_fallback=request.use_ai_fallback
    )


@api.post("/parse/text", response_model=ParseResponse, summary="Parse codes in a text")
@legacy_api.post("/parse/text", response_model=ParseResponse)
async def parse_text_endpoint(request: TextRequest):
    """Extract every standard code from a text string.

    Ranges/lists are expanded into one record per part.
    """
    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Hãy nhập nội dung hoặc mã tiêu chuẩn.")
    records = await run_in_threadpool(
        process_text, text, use_ai_fallback=request.use_ai_fallback
    )
    return {"records": records, "count": len(records)}


@api.post("/parse/files", response_model=FileParseResponse, summary="Parse uploaded documents")
@legacy_api.post("/parse/files", response_model=FileParseResponse)
async def parse_files_endpoint(
    files: list[UploadFile] = File(...),
    use_ai_fallback: bool = Form(False),
):
    """Extract codes from one or more PDF / DOCX / XLSX / XLS / XLSM files."""
    if not files:
        raise HTTPException(status_code=422, detail="Hãy chọn ít nhất một tệp.")

    all_records: list[dict] = []
    file_results: list[dict] = []
    for upload in files:
        suffix = Path(upload.filename or "").suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise HTTPException(
                status_code=415,
                detail=(
                    f"Định dạng {suffix or '(không rõ)'} chưa được hỗ trợ. "
                    "Dùng PDF, DOCX, XLSX, XLS hoặc XLSM."
                ),
            )

        content = await upload.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Mỗi tệp tối đa {MAX_UPLOAD_MB} MB.",
            )

        temp_path = None
        try:
            with NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
                temp_file.write(content)
                temp_path = Path(temp_file.name)
            records = await run_in_threadpool(
                process_document, temp_path, use_ai_fallback=use_ai_fallback
            )
            for record in records:
                record["source_file"] = upload.filename or "uploaded file"
            file_results.append({"filename": upload.filename, "count": len(records)})
            all_records.extend(records)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Không đọc được {upload.filename or 'tệp'}: {exc}",
            ) from exc
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            await upload.close()

    return {
        "records": all_records,
        "count": len(all_records),
        "files": file_results,
    }


app.include_router(api)
app.include_router(legacy_api)
