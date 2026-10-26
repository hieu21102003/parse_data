from pathlib import Path
from parsers.word_table_parser import parse_word_tables

BASE_DIR = Path(__file__).resolve().parents[2]
word_file = BASE_DIR / "data" / "std-qn.docx"

data = parse_word_tables(word_file)
# print(data[:15])

for d in data[:10]:
    print(d)
