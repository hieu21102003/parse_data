import re
from docx import Document
from parsers.std_code_parser import parse_standard_code, parse_standard_code_with_ai_fallback


ROMAN_PATTERN = r"^[IVXLCDM]+$"
LEVEL2_PATTERN = r"^[IVXLCDM]+\.\d+$"


def clean(text):
    return text.replace("\n", " ").strip()


def detect_category(stt, title, raw_code):
    if raw_code != "":
        return None

    if re.match(ROMAN_PATTERN, stt):
        return {
            "level": 1,
            "code": stt,
            "name": title
        }

    if re.match(LEVEL2_PATTERN, stt):
        return {
            "level": 2,
            "code": stt,
            "name": title
        }

    if stt == "":
        return {
            "level": 3,
            "code": None,
            "name": title
        }

    return None


def parse_word_tables(file_path, use_ai_fallback=False):
    doc = Document(file_path)

    records = []

    current_level1 = None
    current_level2 = None
    current_level3 = None
    current_stt = None

    for table in doc.tables:
        for i, row in enumerate(table.rows):
            cells = [clean(c.text) for c in row.cells]

            if i == 0:
                continue  # header

            if len(cells) < 3:
                continue

            stt, title, raw_code = cells[0], cells[1], cells[2]

            # --------------------------------------------------
            # CATEGORY
            # --------------------------------------------------
            cat = detect_category(stt, title, raw_code)
            if cat:
                if cat["level"] == 1:
                    current_level1 = cat
                    current_level2 = None
                    current_level3 = None

                elif cat["level"] == 2:
                    current_level2 = cat
                    current_level3 = None

                elif cat["level"] == 3:
                    current_level3 = cat

                continue

            # --------------------------------------------------
            # STANDARD
            # --------------------------------------------------
            if stt:
                current_stt = stt

            parser = parse_standard_code_with_ai_fallback if use_ai_fallback else parse_standard_code
            parsed = parser(raw_code)

            record = {
                "listing_order": current_stt,
                "title": title,
                "category_level1": current_level1,
                "category_level2": current_level2,
                "category_level3": current_level3,
                **parsed
            }

            records.append(record)

    return records
