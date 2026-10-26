import sys, os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from docx import Document
from parsers.std_code_parser import parse_standard_code


def clean_cell_text(cell):
    return cell.text.replace("\n", " ").replace("\r", "").strip()


def extract_tables_from_word(file_path):
    """
    Đọc tất cả tables trong Word và trả về danh sách record:
    {
        listing_order: STT,
        title: ...,
        parsed_fields...
    }
    """
    doc = Document(file_path)
    records = []

    current_stt = None

    for table in doc.tables:
        for row in table.rows:
            cells = [clean_cell_text(c) for c in row.cells]

            # Skip row rỗng
            if len(cells) < 3:
                continue

            stt, title, raw_code = cells[0], cells[1], cells[2]

            # Handle merged STT (ô trống nghĩa là dùng STT phía trên)
            if stt:
                current_stt = stt

            if not raw_code:
                continue

            parsed = parse_standard_code(raw_code)

            record = {
                "listing_order": current_stt,
                "title": title,
                **parsed
            }

            records.append(record)

    return records
