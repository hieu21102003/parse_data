"""Export pipeline results to a formatted Excel (.xlsx) file.

Exactly eight columns, in this order, and nothing else -- in
particular no ``confidence_score`` or ``explanation`` column, even
though the pipeline's JSON records carry those fields:

    Raw Text | Corrected Code | Standard Name | Organization
    | Main Number | Year | Parts | Suffix

Formatting, as specified:
  - Header row: navy fill, white bold text, centered.
  - Data rows: left-aligned for Raw Text, Corrected Code and Standard Name,
    centered for Organization, Main Number, Year, Parts and Suffix.
  - Column widths are set from the content length (header and
    cells), with a small padding and a cap so one very long code
    cannot blow the sheet out.

Use :func:`export_to_excel` from the pipeline CLI; it returns the
path that was written so the caller can print a confirmation.
"""

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

# (header label, pipeline record key, horizontal alignment)
COLUMNS = (
    ("Raw Text", "raw_text", "left"),
    ("Corrected Code", "corrected_code", "left"),
    ("Standard Name", "standard_name", "left"),
    ("Organization", "organization", "center"),
    ("Main Number", "main_number", "center"),
    ("Year", "year", "center"),
    ("Parts", "parts", "center"),
    ("Suffix", "suffix", "center"),
)

HEADER_FILL = PatternFill(start_color="000080", end_color="000080", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True)
HEADER_ALIGNMENT = Alignment(horizontal="center", vertical="center", wrap_text=True)
# Data cells are vertically centered; text columns wrap
# so a long compound code is still readable when the width is capped.
MAX_COLUMN_WIDTH = 80
_WIDTH_PADDING = 2


def _cell_value(record: dict, key: str):
    """The value for one cell: None/empty becomes a blank cell."""
    value = record.get(key) if isinstance(record, dict) else None
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


def _column_widths(records) -> list[int]:
    """Width per column from the longest header/cell, plus padding."""
    widths = [len(header) for header, _, _ in COLUMNS]
    for record in records or []:
        for index, (_, key, _) in enumerate(COLUMNS):
            value = _cell_value(record, key)
            if value is not None:
                widths[index] = max(widths[index], len(str(value)))
    return [min(width + _WIDTH_PADDING, MAX_COLUMN_WIDTH) for width in widths]


def export_to_excel(records, output_path) -> Path:
    """Write ``records`` (pipeline dicts) to ``output_path`` as .xlsx.

    Only the seven COLUMNS above are written, in order. Parent
    directories are created if needed. Returns the resolved output
    path so the CLI can confirm it to the user.
    """
    path = Path(output_path)
    # Same parent-directory rule as pipeline._ensure_parent_dir:
    # a plain relative name (parent ".") is written straight into
    # the current directory; a path with a directory (e.g.
    # output/ket_qua.xlsx) has that directory created first, so
    # workbook.save() never fails with FileNotFoundError just
    # because the folder is new. No hardcoded /tmp path is used.
    if str(path.parent) not in ("", "."):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RuntimeError(
                f"Could not create output directory {path.parent}: {exc}"
            ) from exc

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Results"
    sheet.freeze_panes = "A2"

    # Header row.
    for col_index, (header, _, _) in enumerate(COLUMNS, start=1):
        cell = sheet.cell(row=1, column=col_index, value=header)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = HEADER_ALIGNMENT

    # Data rows.
    for row_index, record in enumerate(records or [], start=2):
        for col_index, (_, key, alignment) in enumerate(COLUMNS, start=1):
            cell = sheet.cell(row=row_index, column=col_index,
                              value=_cell_value(record, key))
            cell.alignment = Alignment(
                horizontal=alignment, vertical="center",
                wrap_text=(alignment == "left"),
            )

    # Auto-fit column widths from content length.
    for col_index, width in enumerate(_column_widths(records), start=1):
        sheet.column_dimensions[get_column_letter(col_index)].width = width

    # Binary write only: a .xlsx file is a ZIP archive, so it must
    # never be written with write_text() (text mode corrupts it).
    # workbook.save() writes the binary format.
    workbook.save(path)
    return path
