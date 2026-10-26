"""Extract standard-code candidates from text PDFs and Excel workbooks."""

from pathlib import Path
import re

import pandas as pd

try:
    from src.parsers.std_code_parser import parse_standard_code, parse_standard_code_with_ai_fallback
except ModuleNotFoundError:
    from parsers.std_code_parser import parse_standard_code, parse_standard_code_with_ai_fallback


# This is a candidate finder, not a validity check. Add organization prefixes
# here as new source documents introduce additional standards bodies.
STANDARD_CODE_PATTERN = re.compile(
    r"(?<![A-Z0-9])"
    r"(?P<code>(?:TCVN(?:\s*/\s*ISO)?|QCVN|TCCS|ISO(?:\s*/\s*IEC)?|"
    r"IEC|EN(?:\s+ISO)?|BS(?:\s+EN)?|ASTM|JIS|DIN|ANSI|ASME|IEEE|"
    r"SAE|API|AASHTO|AWWA|UL|GB|ГОСТ)\s*[-:]?\s*"
    r"(?:[A-Z]{1,6}\s*)?\d{1,6}(?:[./-]\d{1,6})*"
    r"(?:\s*:\s*\d{4})?(?:\s*/\s*[A-Z0-9Đ-]+)?"
    r"(?:\s*\+\s*(?:AMD|A)\s*\d+(?::\d{4})?)?)",
    re.IGNORECASE,
)


def _text(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).replace("\xa0", " ").strip()


def _extract_from_text(text: str, source: dict, use_ai_fallback: bool) -> list[dict]:
    found = []
    for match in STANDARD_CODE_PATTERN.finditer(text or ""):
        raw_code = re.sub(r"\s+", " ", match.group("code")).strip(" .;,|\t\r\n")
        if not raw_code:
            continue
        parsed = (
            parse_standard_code_with_ai_fallback(raw_code)
            if use_ai_fallback
            else parse_standard_code(raw_code)
        )
        found.append({"code": raw_code, **source, "parsed": parsed})
    return found


def _deduplicate(records: list[dict]) -> list[dict]:
    unique = []
    seen = {}
    for record in records:
        key = re.sub(r"\s+", " ", record["code"]).strip().upper()
        if key not in seen:
            seen[key] = len(unique)
            unique.append(record)
        elif record.get("row") is not None and unique[seen[key]].get("row") is None:
            # Prefer the table/sheet row location over a page-wide text match.
            unique[seen[key]] = record
    return unique


def extract_standard_codes_from_pdf(file_path, use_ai_fallback=False) -> list[dict]:
    """Extract codes from every page of a text-based PDF.

    Scans page text and table rows, so codes need not be in a dedicated column.
    The result records the PDF page where each distinct code first appears.
    """
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("PDF extraction requires pdfplumber; install project dependencies") from exc

    path = Path(file_path)
    records = []
    with pdfplumber.open(path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            page_text = page.extract_text() or ""
            records.extend(_extract_from_text(
                page_text,
                {"file": str(path), "page": page_number, "row": None},
                use_ai_fallback,
            ))

            # Table extraction can preserve row groupings that plain text loses.
            for row_number, row in enumerate(page.extract_tables() or [], start=1):
                row_text = " | ".join(_text(cell) for cell in row if _text(cell))
                records.extend(_extract_from_text(
                    row_text,
                    {"file": str(path), "page": page_number, "row": row_number},
                    use_ai_fallback,
                ))
    return _deduplicate(records)


def extract_standard_codes_from_excel(file_path, use_ai_fallback=False) -> list[dict]:
    """Scan every cell in every sheet of an Excel workbook for code candidates."""
    path = Path(file_path)
    try:
        sheets = pd.read_excel(path, sheet_name=None, header=None, dtype=str)
    except ImportError as exc:
        raise RuntimeError(
            "Excel extraction requires openpyxl for .xlsx or xlrd for .xls"
        ) from exc

    records = []
    for sheet_name, frame in sheets.items():
        for row_index, values in frame.iterrows():
            row_text = " | ".join(value for value in (_text(v) for v in values) if value)
            records.extend(_extract_from_text(
                row_text,
                {"file": str(path), "sheet": sheet_name, "row": int(row_index) + 1},
                use_ai_fallback,
            ))
    return _deduplicate(records)


def extract_standard_codes(file_path, use_ai_fallback=False) -> list[dict]:
    """Dispatch PDF or Excel files to the matching standard-code extractor."""
    suffix = Path(file_path).suffix.lower()
    if suffix == ".pdf":
        return extract_standard_codes_from_pdf(file_path, use_ai_fallback)
    if suffix in {".xlsx", ".xls", ".xlsm"}:
        return extract_standard_codes_from_excel(file_path, use_ai_fallback)
    raise ValueError(f"Unsupported file type: {suffix}. Supported: PDF, XLSX, XLS, XLSM")
