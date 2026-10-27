"""Extract standard-code candidates from PDFs, DOCX and Excel workbooks.

This is the generic multi-format ingestion layer. It scans *all* text
(paragraphs, table cells, PDF pages/tables, Excel cells) for candidate
codes. It is different from ``src/parsers/word_table_parser.py``, which
only understands DOCX tables with a fixed STT / title / code layout.
"""

from pathlib import Path
import re

import pandas as pd

try:
    from src.parsers.std_code_parser import parse_standard_code, parse_standard_code_with_ai_fallback
except ModuleNotFoundError:
    from parsers.std_code_parser import parse_standard_code, parse_standard_code_with_ai_fallback


# This is a candidate finder, not a validity check. Add organization prefixes
# here as new source documents introduce additional standards bodies.
_STANDARD_CODE_CORE = (
    r"(?:TCVN(?:\s*/\s*ISO)?|QCVN|TCCS|ISO(?:\s*/\s*IEC)?|"
    r"IEC|EN(?:\s+ISO)?|BS(?:\s+EN)?|ASTM|JIS|DIN|ANSI|ASME|IEEE|"
    r"SAE|API|AASHTO|AWWA|UL|GB|ГОСТ)\s*[-:]?\s*"
    # Spaces around the hyphen/dot/slash separators are just
    # spacing, e.g. "ISO 3452 -1 đến 6" is ISO 3452, part range
    # 1-6. The deterministic parser already handles that form,
    # but without \s* here the candidate stopped at the main
    # number ("ISO 3452"), so an equivalent code inside
    # parentheses lost its parts and its parenthetical was
    # stripped as prose instead of being kept as an equivalent.
    r"(?:[A-Z]{1,6}\s*)?\d{1,6}(?:\s*[./-]\s*\d{1,6})*"
    # Optional comma list after the first part, e.g.
    # "TCVN 13566-1,2,3,4,5:2022" or "1, 2, 3, 4 và 5".
    # Each comma number is 1-3 digits followed by a non-digit,
    # so a 4-digit year after a comma (", 2020") is never
    # swallowed as a part, and a comma followed by another code
    # ("-1, TCVN ...") does not match at all.
    r"(?:\s*,\s*\d{1,3}(?!\d)(?:\s*(?:,|và|and)\s*\d{1,3}(?!\d))*)?"
    r"(?:\s*:\s*\d{4})?(?:\s*/\s*[A-Z0-9Đ-]+(?::\s*\d{4})?)?"
    r"(?:\s*\+\s*(?:AMD|A)\s*\d+(?::\d{4})?)?"
    # Optional Vietnamese range outside parentheses, e.g.
    # "TCVN 13566 từ 1 đến 10:2019" or "TCVN 13566-1 đến 10:2019".
    # The endpoint is limited to 1-3 digits with (?!\d) so a
    # sentence date range such as "TCVN 1234:2020 đến 2025" is
    # NOT captured as a part range.
    r"(?:\s*(?:từ|from)\s*-?\s*\d{1,3}(?!\d)\s*(?:đến|tới|to)\s*(?:phần\s*)?\d{1,3}(?!\d)(?:\s*:\s*\d{4})?(?:\s*/\s*[A-Z0-9Đ-]+(?::\s*\d{4})?)?)?"
    r"(?:\s*(?:đến|tới)\s*(?:phần\s*)?\d{1,3}(?!\d)(?:\s*:\s*\d{4})?(?:\s*/\s*[A-Z0-9Đ-]+(?::\s*\d{4})?)?)?"
)
_STANDARD_CODE_PREFIX = r"(?<![A-Z0-9])(?P<code>"
STANDARD_CODE_BASE_PATTERN = re.compile(
    _STANDARD_CODE_PREFIX + _STANDARD_CODE_CORE + r")",
    re.IGNORECASE,
)
# Keep a possible parenthetical note available to the parser, but validate it
# before returning it as part of raw_text. A broad [^)]* here used to swallow
# whole descriptions (and every later part code) into one candidate.
STANDARD_CODE_PATTERN = re.compile(
    _STANDARD_CODE_PREFIX + _STANDARD_CODE_CORE + r"(?:\s*\([^)]*\))?)",
    re.IGNORECASE,
)

# A parenthetical note is a part range/list (kept, for the parser)
# when it matches one of the forms below. The "từ" forms must
# allow the part keyword on either side of the range -- "từ
# phần 1 đến 10", "từ 1 đến phần 10", "từ phần 1 đến phần
# 10" -- and a hyphen separator ("từ 1 - 10"): the parser
# already understands all of these, but this pattern used to
# reject them, so clean_code_candidate() stripped the whole
# note before the parser ever saw it and the parts were lost.
# Endpoints stay 1-3 digits so a date range such as "từ 2020
# đến 2025" is still rejected here (its endpoints are years).
_PART_NOTE = re.compile(
    r"(?:"
    r"(?:(?:từ|from)\s+)?(?:các\s+)?phần(?:\s+từ)?\s*-?\s*\d{1,3}"
    r"(?:\s*(?:-|đến|tới|to|,|và)\s*(?:phần\s*)?\d{1,4})*"
    r"|(?:from\s+)?parts?\s*-?\s*\d{1,3}(?:\s*(?:-|to|,|and)\s*(?:part\s*)?\d{1,4})*"
    r"|(?:từ|from)\s*(?:(?:phần|part)\s*)?-?\s*\d{1,3}\s*(?:-|–|—|đến|tới|to)\s*(?:(?:phần|part)\s*)?\d{1,3}"
    r"(?:\s*[,;]\s*(?:19|20|21)\d{2})?"
    r"|(?:rev(?:ision)?|version|bản\s+sửa\s+đổi|amendment)\s*[\w.-]+"
    r"|(?:19|20|21)\d{2}"
    r")",
    re.IGNORECASE,
)


def _strip_invalid_slash_suffix(raw_code: str) -> str:
    """Strip a trailing ``/<word>`` that is not a real suffix.

    The extractor pattern's suffix group (``/<token>``) is
    case-insensitive, so a description that follows a code in the
    same cell -- ``TCVN 13594-1:2022 / Tiêu chuẩn về bê tông`` --
    used to be captured as ``TCVN 13594-1:2022 / Ti`` (the token
    stops at the first non-ASCII letter) and pollute both
    ``raw_code`` and the parser's ``suffix``.

    A trailing slash token is kept only when it is plausibly a
    suffix, i.e. it carries a ``:YYYY`` year (``/AC:2009``), a digit
    (``/A1``), a known amendment form (``/ac``, ``/amd2``), or it is
    all-uppercase (``/BXD``, ``/TCĐBVN``). Anything else -- a
    mixed-case word such as ``Ti`` -- is the start of a description,
    not a suffix, so the whole ``/<word>`` fragment is removed.
    A bare lowercase word that is not a known amendment is
    indistinguishable from the start of a Vietnamese description,
    so it is stripped too; write real suffixes in uppercase or
    with their year. An all-caps first word after a slash is
    inherently ambiguous with a suffix token and is kept.
    """
    match = re.search(r"\s*/\s*([^\s/]+)$", raw_code)
    if not match:
        return raw_code
    token = match.group(1)
    if ":" in token:
        head, _, year = token.partition(":")
        if head and year.isdigit() and len(year) == 4:
            return raw_code
        return raw_code[:match.start()].rstrip()
    if any(ch.isdigit() for ch in token):
        return raw_code
    if token.lower() in {"ac"} or re.fullmatch(r"a\d+|amd\d+", token.lower()):
        return raw_code
    letters = [ch for ch in token if ch.isalpha()]
    if letters and all(ch.isupper() for ch in letters):
        return raw_code
    return raw_code[:match.start()].rstrip()


def clean_code_candidate(raw_code: str) -> str:
    """Strip arbitrary prose accidentally captured as a parenthetical note.

    The return value is always *just the matched code* (plus a kept
    part-range / equivalent-code parenthetical, which the parser
    needs): never the surrounding row, paragraph or cell text.
    """
    raw_code = re.sub(r"\s+", " ", raw_code or "").strip(" .;,|\t\r\n")
    open_paren = raw_code.find("(")
    if open_paren < 0 or not raw_code.endswith(")"):
        return _strip_invalid_slash_suffix(raw_code)

    note = raw_code[open_paren + 1:-1].strip()
    if _PART_NOTE.fullmatch(note):
        return _strip_invalid_slash_suffix(raw_code)

    # Parenthetical equivalents are retained only when the note consists
    # entirely of one or more standard codes, without descriptive prose.
    remainder = STANDARD_CODE_BASE_PATTERN.sub("", note)
    remainder = re.sub(r"[\s,;|&+]+", "", remainder)
    if not remainder and STANDARD_CODE_BASE_PATTERN.search(note):
        return _strip_invalid_slash_suffix(raw_code)

    return _strip_invalid_slash_suffix(raw_code[:open_paren].rstrip())


def extract_first_clean_code(text: str) -> str | None:
    """Return the first cleaned standard code found in ``text``.

    This is the single place that turns an arbitrary row, paragraph
    or cell string into a code: it finds the first regex match and
    runs it through :func:`clean_code_candidate`, so the result
    never contains the surrounding description. Returns ``None``
    when no standard-code match is found (e.g. an unknown org such
    as ``XYZ 1234:2020``, which the pattern does not cover, or a
    string with no code at all); callers keep the original string
    in that case instead of inventing a code.
    """
    if not text:
        return None
    for match in STANDARD_CODE_PATTERN.finditer(text):
        code = clean_code_candidate(match.group("code"))
        if code:
            return code
    return None


def _text(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).replace("\xa0", " ").strip()


_TITLE_HEADER = re.compile(
    r"(?:tên(?:\s+tiêu\s+chuẩn)?|tên\s+gọi|tiêu\s+đề|title|standard\s+name|name|description|mô\s+tả)",
    re.IGNORECASE,
)
_CODE_HEADER = re.compile(
    r"(?:mã|ký\s+hiệu|code|standard\s+number|standard\s+code|số\s+hiệu)",
    re.IGNORECASE,
)
_NON_TITLE = re.compile(
    r"^(?:stt|no\.?|số\s+tt|mã(?:\s+tiêu\s+chuẩn)?|ký\s+hiệu|code|standard\s+code|"
    r"năm|year|ghi\s+chú|note|đơn\s+vị|tình\s+trạng)$",
    re.IGNORECASE,
)


def _find_title_column(rows) -> int | None:
    """Return a title/name column from a table header, if one is present."""
    for row in list(rows)[:10]:
        values = [_text(value) for value in row]
        if not any(_CODE_HEADER.search(value) for value in values):
            continue
        for index, value in enumerate(values):
            if _TITLE_HEADER.search(value):
                return index
    return None


def _standard_name_from_row(cells, title_column: int | None = None) -> str | None:
    """Best-effort title association for one table row.

    Prefer a column explicitly labeled as a standard title. For headerless
    tables, remove code-shaped text and use the clearest remaining text cell.
    """
    values = [_text(cell) for cell in cells]
    if title_column is not None and title_column < len(values):
        title = values[title_column]
        if title and not _TITLE_HEADER.fullmatch(title):
            return title

    candidates = []
    for value in values:
        if not value or _NON_TITLE.fullmatch(value):
            continue
        residual = STANDARD_CODE_PATTERN.sub(" ", value)
        residual = re.sub(r"[|;,:()\-–—]+", " ", residual)
        residual = re.sub(r"\s+", " ", residual).strip()
        # If the code occupied the whole cell, this cell is not a title.
        if residual and not _TITLE_HEADER.fullmatch(residual) and not residual.isdigit():
            candidates.append(residual)
        elif not STANDARD_CODE_PATTERN.search(value) and len(value) > 4:
            candidates.append(value)
    if not candidates:
        return None
    # The table's name/description is usually the longest meaningful text
    # cell; numeric identifiers and short labels have already been excluded.
    return max(candidates, key=len)


_PART_TITLE_MARKER = re.compile(
    r"(Phần|Part)\s+(\d{1,3})\s*(?::|：)?",
    re.IGNORECASE,
)


def _split_part_titles(name: str):
    """Split a part-list title into (base title, {part number: part title}).

    A title such as::

        Cầu đường sắt khổ 1435, tốc độ đến 350 km/h
        - Phần 1: Quy định chung, Phần 2: Thiết kế tổng thể, ...

    is one base title plus one title per part. The base is the text
    before the first ``Phần N`` marker; each part title is the text
    between its marker and the next marker (or the end of the string),
    with list separators stripped. Returns ``None`` when the name
    does not contain at least two part markers, i.e. when it is not
    a part list at all -- in that case there is nothing to split.
    """
    markers = list(_PART_TITLE_MARKER.finditer(name or ""))
    if len(markers) < 2:
        return None
    base = name[:markers[0].start()].strip(" \t\r\n,;:–—-")
    by_part = {}
    for index, marker in enumerate(markers):
        part_number = int(marker.group(2))
        end = markers[index + 1].start() if index + 1 < len(markers) else len(name)
        segment = name[marker.end():end].strip(" \t\r\n,;:–—-")
        if segment and part_number not in by_part:
            by_part[part_number] = segment
    if len(by_part) < 2:
        return None
    return base, by_part


def standard_name_for_parts(name, parsed) -> str | None:
    """Return the standard name that matches one parsed record's part.

    When ``name`` is a part-list title (see :func:`_split_part_titles`)
    and the record has exactly one part, the record gets only its
    own part's title, prefixed with the shared base title::

        TCVN 13594-1:2022 -> "Cầu đường sắt khổ 1435, tốc độ đến
                              350 km/h - Phần 1: Quy định chung"
        TCVN 13594-2:2022 -> "Cầu đường sắt khổ 1435, tốc độ đến
                              350 km/h - Phần 2: Thiết kế tổng thể"

    instead of the whole 10-part list repeated on every row.
    Every other case falls back to the full name unchanged, so
    nothing is ever lost by splitting: no part (e.g. ``TCVN
    13594:2022``), a part range (``std_parts`` has two endpoints,
    e.g. ``["1", "10"]``), a part number not listed in the title,
    or a title that is not a part list at all.
    """
    if not name or not parsed:
        return name
    parts = parsed.get("std_parts") or []
    if len(parts) != 1:
        return name
    try:
        part_number = int(str(parts[0]).strip())
    except (TypeError, ValueError):
        return name
    split = _split_part_titles(name)
    if split is None:
        return name
    base, by_part = split
    part_title = by_part.get(part_number)
    if not part_title:
        return name
    word = "Phần" if "phần" in name.lower() else "Part"
    if base:
        return f"{base} - {word} {part_number}: {part_title}"
    return f"{word} {part_number}: {part_title}"


def _inner_codes_from_parentheticals(raw_code: str) -> list[str]:
    """Codes hidden inside parentheses of an outer match.

    E.g. ``TCVN 13695-1 đến 10:2023 (BS EN 13146-1 đến 10:2019)``
    is two codes, not one: the outer match consumes the whole
    string, so without this the BS EN code (and its year 2019)
    would never be emitted as its own record. Closed and unclosed
    parentheticals are both handled; the outer code itself is
    never returned here.
    """
    inner = []
    outer_key = re.sub(r"\s+", " ", raw_code).strip().upper()
    for note in re.findall(r"\(([^)]*)\)", raw_code):
        for match in STANDARD_CODE_BASE_PATTERN.finditer(note):
            code = clean_code_candidate(match.group("code"))
            if code and re.sub(r"\s+", " ", code).strip().upper() != outer_key:
                inner.append(code)
    # Unclosed trailing parenthetical: "(BS EN ... 2019" with no ")".
    if "(" in raw_code and raw_code.count("(") > raw_code.count(")"):
        tail = raw_code.rsplit("(", 1)[-1]
        for match in STANDARD_CODE_BASE_PATTERN.finditer(tail):
            code = clean_code_candidate(match.group("code"))
            if code and re.sub(r"\s+", " ", code).strip().upper() != outer_key:
                inner.append(code)
    return inner


def _extract_from_text(text: str, source: dict, use_ai_fallback: bool) -> list[dict]:
    """Extract codes from one text string (one cell, one paragraph, one page).

    Only the cleaned matched code is ever emitted as ``"code"``:
    the input string itself -- a whole row, paragraph or cell that
    may contain a long description -- is never copied into a
    record. Table callers must use :func:`_extract_from_cells`,
    which scans each cell separately, instead of joining a row's
    cells into one ``" | "`` string and scanning that.
    """
    found = []
    for match in STANDARD_CODE_PATTERN.finditer(text or ""):
        matched_code = match.group("code")
        raw_code = clean_code_candidate(matched_code)
        if not raw_code:
            continue
        parsed = (
            parse_standard_code_with_ai_fallback(raw_code)
            if use_ai_fallback
            else parse_standard_code(raw_code)
        )
        record = {"code": raw_code, **source, "parsed": parsed}
        if "standard_name" in source:
            # A row's title may be a whole part list; give this
            # record only the title of its own part (falling back
            # to the full title when it cannot be matched).
            record["standard_name"] = standard_name_for_parts(
                source.get("standard_name"), parsed
            )
        found.append(record)
        # Emit the equivalent code(s) inside the parentheses as
        # their own records, with their own range and year intact.
        for inner_code in _inner_codes_from_parentheticals(matched_code):
            inner_parsed = (
                parse_standard_code_with_ai_fallback(inner_code)
                if use_ai_fallback
                else parse_standard_code(inner_code)
            )
            inner_record = {"code": inner_code, **source, "parsed": inner_parsed}
            if "standard_name" in source:
                inner_record["standard_name"] = standard_name_for_parts(
                    source.get("standard_name"), inner_parsed
                )
            found.append(inner_record)
    return found


def _extract_from_cells(cells, source: dict, use_ai_fallback: bool) -> list[dict]:
    """Scan cells independently so a title cell never joins a code candidate."""
    found = []
    for cell in cells:
        value = _text(cell)
        if value:
            found.extend(_extract_from_text(value, source, use_ai_fallback))
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
            for table_number, table in enumerate(page.extract_tables() or [], start=1):
                title_column = _find_title_column(table)
                for row_number, row in enumerate(table, start=1):
                    records.extend(_extract_from_cells(
                        row,
                        {
                            "file": str(path), "page": page_number,
                            "table": table_number, "row": row_number,
                            "standard_name": _standard_name_from_row(row, title_column),
                        },
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
        rows = frame.values.tolist()
        title_column = _find_title_column(rows)
        for row_index, values in frame.iterrows():
            cells = [_text(value) for value in values]
            records.extend(_extract_from_cells(
                cells,
                {
                    "file": str(path), "sheet": sheet_name,
                    "row": int(row_index) + 1,
                    "standard_name": _standard_name_from_row(cells, title_column),
                },
                use_ai_fallback,
            ))
    return _deduplicate(records)


def extract_standard_codes_from_docx(file_path, use_ai_fallback=False) -> list[dict]:
    """Extract codes from every paragraph and table cell of a DOCX file.

    Paragraphs and tables are scanned as plain text, so codes need not be
    in a dedicated code column. The result records the paragraph index
    and/or table/row where each distinct code first appears.
    """
    try:
        from docx import Document
    except ImportError as exc:
        raise RuntimeError("DOCX extraction requires python-docx; install project dependencies") from exc

    path = Path(file_path)
    doc = Document(str(path))
    records = []

    for para_number, paragraph in enumerate(doc.paragraphs, start=1):
        records.extend(_extract_from_text(
            paragraph.text or "",
            {"file": str(path), "paragraph": para_number, "table": None, "row": None},
            use_ai_fallback,
        ))

    for table_number, table in enumerate(doc.tables, start=1):
        table_rows = [[cell.text for cell in row.cells] for row in table.rows]
        title_column = _find_title_column(table_rows)
        for row_number, row in enumerate(table.rows, start=1):
            records.extend(_extract_from_cells(
                [cell.text for cell in row.cells],
                {
                    "file": str(path), "paragraph": None,
                    "table": table_number, "row": row_number,
                    "standard_name": _standard_name_from_row(
                        table_rows[row_number - 1], title_column
                    ),
                },
                use_ai_fallback,
            ))
    return _deduplicate(records)


def extract_standard_codes(file_path, use_ai_fallback=False) -> list[dict]:
    """Dispatch PDF, DOCX or Excel files to the matching standard-code extractor."""
    suffix = Path(file_path).suffix.lower()
    if suffix == ".pdf":
        return extract_standard_codes_from_pdf(file_path, use_ai_fallback)
    if suffix == ".docx":
        return extract_standard_codes_from_docx(file_path, use_ai_fallback)
    if suffix in {".xlsx", ".xls", ".xlsm"}:
        return extract_standard_codes_from_excel(file_path, use_ai_fallback)
    raise ValueError(f"Unsupported file type: {suffix}. Supported: PDF, DOCX, XLSX, XLS, XLSM")
