"""FastAPI wrapper around the existing standard-code pipeline."""

from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.pipeline import process_document, process_text


ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / "frontend"
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".xls", ".xlsm"}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

app = FastAPI(title="Standards AI", version="0.1.0")
app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")


class TextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    use_ai_fallback: bool = False


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/parse/text")
def parse_text(request: TextRequest):
    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Hãy nhập nội dung hoặc mã tiêu chuẩn.")
    records = process_text(text, use_ai_fallback=request.use_ai_fallback)
    return {"records": records, "count": len(records)}


@app.post("/api/parse/files")
async def parse_files(
    files: list[UploadFile] = File(...),
    use_ai_fallback: bool = Form(False),
):
    if not files:
        raise HTTPException(status_code=422, detail="Hãy chọn ít nhất một tệp.")

    all_records = []
    file_results = []
    for upload in files:
        suffix = Path(upload.filename or "").suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise HTTPException(
                status_code=415,
                detail=f"Định dạng {suffix or '(không rõ)'} chưa được hỗ trợ. Dùng PDF, DOCX, XLSX, XLS hoặc XLSM.",
            )

        content = await upload.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Mỗi tệp tối đa 25 MB.")

        temp_path = None
        try:
            with NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
                temp_file.write(content)
                temp_path = Path(temp_file.name)
            records = process_document(temp_path, use_ai_fallback=use_ai_fallback)
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

    return {"records": all_records, "count": len(all_records), "files": file_results}
