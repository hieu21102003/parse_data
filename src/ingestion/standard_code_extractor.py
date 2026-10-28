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
    # "GB/T" (recommended) and "GB/Z" (guidance) are distinct
    # Chinese designations, not "GB" plus a suffix: without the
    # "/T" here a "GB/T 44413-2024" candidate never matched at
    # all. "CISPR" (IEC radio-interference committee) likewise.
    r"SAE|API|AASHTO|AWWA|UL|CISPR|GB(?:\s*/\s*[TZ])?|ГОСТ)\s*[-:]?\s*"
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


# -------------------------------------------------
# Hierarchy context: section headings above the codes.
#
# Catalogs ("Danh mục tiêu chuẩn") group codes under headings:
#   level 1 -- a Roman numeral: "I", "II", "III", ...
#   level 2 -- a dotted subsection: "I.1", "I.2", "I.2.1",
#              or the same numbering with Arabic digits ("1.2."),
#              or a numbered sub-heading in the code column
#              ("2. Thiết kế") under a level-2 heading.
# A record carries the nearest heading of each kind in
# "parent_level_1" / "parent_level_2", plus the row's "stt"
# (TT column) when the table has one. The spec's JSON calls the
# code itself "standard_code"; here that is "corrected_code"
# and the title is "standard_name".
# -------------------------------------------------

_ROMAN_NUMERAL = re.compile(
    r"^(M{0,3})(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$"
)


def _is_roman_numeral(value: str) -> bool:
    """True for a strict Roman numeral (I..XXXIX), nothing else."""
    if not value:
        return False
    match = _ROMAN_NUMERAL.match(value)
    return bool(match) and any(match.groups())


_DOTTED_MARKER = re.compile(r"^(?P<first>[IVXLCDM]+|\d+)(?P<rest>(?:\.\d+)+)\.?$")
_BARE_NUMBERED = re.compile(r"^(?P<marker>\d{1,2})\.\s+(?P<title>\S.*)$")


def parse_heading_text(text: str, *, allow_bare_numbered: bool = False):
    """Parse one heading line into ``(level, label)`` or ``None``.

    Level 1 is a bare Roman numeral (``I. Nhóm ...``); level 2
    is a dotted subsection (``I.2.1. Chung ...``, ``1.2. ...``).
    The label is the marker (trailing dot stripped) plus the
    title, e.g. ``"I.2.1. Chung, tuyến, ..."``. A bare numbered
    line (``2. Thiết kế``) is only a heading when
    ``allow_bare_numbered`` is set: in table rows the empty STT
    cell makes it structural, while in free text a ``"1. ..."``
    line is too often an ordinary numbered sentence.
    """
    if not text:
        return None
    line = re.sub(r"\s+", " ", str(text).replace("\xa0", " ")).strip()
    if not line:
        return None
    # Dotted subsection first: "I.2.1. ..." must not be read as
    # a bare Roman "I" followed by a title starting with "2.1.".
    dotted = _DOTTED_MARKER.match(line.split(None, 1)[0]) if " " in line else None
    if dotted:
        first, rest = dotted.group("first"), dotted.group("rest")
        if first.isdigit() or _is_roman_numeral(first):
            title = line.split(None, 1)[1].strip()
            if title:
                marker = (first + rest).rstrip(".")
                return 2, f"{marker}. {title}"
    # Bare Roman numeral: "I. Nhóm ..." / "II Nhóm ...".
    head, _, title = line.partition(" ")
    roman = head.rstrip(".")
    if _is_roman_numeral(roman) and title.strip():
        return 1, f"{roman}. {title.strip()}"
    # Bare numbered sub-heading, table rows only (see docstring).
    if allow_bare_numbered:
        bare = _BARE_NUMBERED.match(line)
        if bare:
            return 2, f"{bare.group('marker')}. {bare.group('title').strip()}"
    return None


def _heading_from_row(cells) -> tuple[int, str] | None:
    """Heading of one table row, or ``None`` when it is not one.

    Heading rows in the real catalogs put the marker in the
    first cell and the title in the next (``I`` / ``Nhóm ...``,
    ``I.1`` / ``Quy chuẩn kỹ thuật``), or the whole heading in
    a single merged cell, or a numbered sub-heading in the code
    column with an empty STT cell (``""`` / ``2. Thiết kế``).
    A row containing a standard code is never a heading row:
    the code is extracted with the current context instead.
    """
    values = [_text(cell) for cell in cells]
    non_empty = [(i, v) for i, v in enumerate(values) if v]
    if not non_empty:
        return None
    joined = " ".join(v for _, v in non_empty)
    if STANDARD_CODE_PATTERN.search(joined):
        return None
    if len(non_empty) == 1:
        return parse_heading_text(non_empty[0][1], allow_bare_numbered=True)
    first_index, first = non_empty[0]
    # Bare marker in the first cell, title in the next one.
    marker_match = _DOTTED_MARKER.match(first.rstrip("."))
    pure_roman = _is_roman_numeral(first.rstrip("."))
    if marker_match or pure_roman:
        if marker_match:
            marker_first = marker_match.group("first")
            if not (marker_first.isdigit() or _is_roman_numeral(marker_first)):
                return None
        title = non_empty[1][1]
        marker = first.rstrip(".")
        level = 1 if pure_roman and not marker_match else 2
        return level, f"{marker}. {title}"
    # Marker and title together in the first cell.
    parsed = parse_heading_text(first)
    if parsed:
        return parsed
    # Numbered sub-heading sitting in a later column with the
    # cells before it empty (an empty STT cell in the real files).
    if first_index > 0:
        return parse_heading_text(first, allow_bare_numbered=True)
    return None


class _HierarchyContext:
    """Current section headings while scanning one file (or sheet).

    Level 1 is the Roman-numeral group; ``sub`` is the nearest
    subsection heading below it. A new level-1 heading clears
    the subsection; a subsection heading replaces the previous
    one. ``snapshot()`` is what each code record carries.
    """

    def __init__(self):
        self.level1 = None
        self.sub = None

    def update(self, heading) -> None:
        level, label = heading
        if level == 1:
            self.level1 = label
            self.sub = None
        else:
            self.sub = label

    def snapshot(self) -> dict:
        return {"parent_level_1": self.level1, "parent_level_2": self.sub}

    def reset(self) -> None:
        self.level1 = None
        self.sub = None


def _find_stt_column(rows) -> int | None:
    """Index of the TT/STT column of a table, or ``None``.

    A header row labels its first column ``TT`` (or ``STT``)
    next to a code/title header. Without such a header the
    column is not guessed: inventing an STT from a numeric
    first cell would mislabel heading markers and years.
    """
    fallback = None
    for row in rows or []:
        values = [_text(value) for value in row]
        for index, value in enumerate(values):
            if value.upper() in ("TT", "STT"):
                if any(_CODE_HEADER.search(v) or _TITLE_HEADER.search(v) for v in values):
                    return index
                if fallback is None:
                    fallback = index
    return fallback


def _stt_from_row(cells, stt_column: int | None) -> str | None:
    """The row's STT value, verbatim, or ``None``.

    Only a plain integer (optionally with a trailing dot, as
    some sheets write ``"1."``) in the TT column counts; a
    heading marker (``I``, ``I.1``) in that column is not an
    STT, and heading rows never reach this function.
    """
    if stt_column is None or stt_column >= len(cells):
        return None
    value = _text(cells[stt_column])
    match = re.fullmatch(r"(\d+)\.?", value)
    return match.group(1) if match else None


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


def _line_contexts(text: str, context: "_HierarchyContext") -> list[tuple[int, dict]]:
    """Hierarchy snapshot in effect for each line of ``text``.

    Heading lines (Roman / dotted markers, with no code on the
    line) update the shared ``context`` as scanning proceeds, so
    a heading on one line governs the codes on the lines below
    it. Matching itself is unchanged: codes are still found by
    one scan over the whole string, and each match takes the
    snapshot of the line where it starts.
    """
    snapshots = []
    offset = 0
    for line in (text or "").splitlines(keepends=True):
        stripped = line.strip()
        if stripped and not STANDARD_CODE_PATTERN.search(line):
            heading = parse_heading_text(stripped)
            if heading:
                context.update(heading)
        snapshots.append((offset, context.snapshot()))
        offset += len(line)
    if not snapshots:
        snapshots.append((0, context.snapshot()))
    return snapshots


def _snapshot_at(snapshots: list[tuple[int, dict]], position: int) -> dict:
    current = snapshots[0][1]
    for offset, snapshot in snapshots:
        if offset > position:
            break
        current = snapshot
    return current


def _extract_from_text(text: str, source: dict, use_ai_fallback: bool,
                       context: "_HierarchyContext | None" = None) -> list[dict]:
    """Extract codes from one text string (one cell, one paragraph, one page).

    Only the cleaned matched code is ever emitted as ``"code"``:
    the input string itself -- a whole row, paragraph or cell that
    may contain a long description -- is never copied into a
    record. Table callers must use :func:`_extract_from_cells`,
    which scans each cell separately, instead of joining a row's
    cells into one ``" | "`` string and scanning that.

    Each record also carries the hierarchy context in effect
    where its code appears (``parent_level_1`` / ``parent_level_2``)
    and the row's ``stt`` when the caller put one in ``source``.
    A shared ``context`` object lets headings in earlier text
    govern later text (paragraphs before tables, pages before
    tables); without one, a fresh context starts empty.
    """
    ctx = context if context is not None else _HierarchyContext()
    snapshots = _line_contexts(text or "", ctx)
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
        record = {
            "code": raw_code, **source, "parsed": parsed,
            **_snapshot_at(snapshots, match.start()),
        }
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
            inner_record = {
                "code": inner_code, **source, "parsed": inner_parsed,
                **_snapshot_at(snapshots, match.start()),
            }
            if "standard_name" in source:
                inner_record["standard_name"] = standard_name_for_parts(
                    source.get("standard_name"), inner_parsed
                )
            found.append(inner_record)
    return found


def _extract_from_cells(cells, source: dict, use_ai_fallback: bool,
                        context: "_HierarchyContext | None" = None,
                        stt_column: int | None = None) -> list[dict]:
    """Scan cells independently so a title cell never joins a code candidate.

    A heading row updates the shared hierarchy ``context`` and
    yields no records; a code row yields records carrying the
    current context snapshot and the row's ``stt``.
    """
    ctx = context if context is not None else _HierarchyContext()
    heading = _heading_from_row(cells)
    if heading:
        ctx.update(heading)
        return []
    row_source = {**source, "stt": _stt_from_row(cells, stt_column)}
    found = []
    for cell in cells:
        value = _text(cell)
        if value:
            found.extend(_extract_from_text(value, row_source, use_ai_fallback, ctx))
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
    # One hierarchy context for the whole file: a heading on an
    # early page governs codes on later pages until replaced.
    context = _HierarchyContext()
    with pdfplumber.open(path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            page_text = page.extract_text() or ""
            records.extend(_extract_from_text(
                page_text,
                {"file": str(path), "page": page_number, "row": None},
                use_ai_fallback,
                context,
            ))

            # Table extraction can preserve row groupings that plain text loses.
            for table_number, table in enumerate(page.extract_tables() or [], start=1):
                title_column = _find_title_column(table)
                stt_column = _find_stt_column(table)
                for row_number, row in enumerate(table, start=1):
                    records.extend(_extract_from_cells(
                        row,
                        {
                            "file": str(path), "page": page_number,
                            "table": table_number, "row": row_number,
                            "standard_name": _standard_name_from_row(row, title_column),
                        },
                        use_ai_fallback,
                        context,
                        stt_column,
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
        stt_column = _find_stt_column(rows)
        # A fresh hierarchy per sheet: sheets are separate
        # catalogs, so a heading from one must not leak into
        # the next.
        context = _HierarchyContext()
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
                context,
                stt_column,
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
    # One hierarchy context for the whole document, scanned in
    # document order: a heading paragraph governs the tables
    # that follow it. Iterating doc.paragraphs then doc.tables
    # would lose that order, so walk the body elements directly.
    context = _HierarchyContext()
    try:
        from docx.table import Table as _DocxTable
        from docx.text.paragraph import Paragraph as _DocxParagraph
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise RuntimeError("DOCX extraction requires python-docx") from exc

    para_number = 0
    table_number = 0
    for child in doc.element.body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag == "p":
            para_number += 1
            paragraph = _DocxParagraph(child, doc)
            records.extend(_extract_from_text(
                paragraph.text or "",
                {"file": str(path), "paragraph": para_number, "table": None, "row": None},
                use_ai_fallback,
                context,
            ))
        elif tag == "tbl":
            table_number += 1
            table = _DocxTable(child, doc)
            table_rows = [[cell.text for cell in row.cells] for row in table.rows]
            title_column = _find_title_column(table_rows)
            stt_column = _find_stt_column(table_rows)
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
                    context,
                    stt_column,
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
