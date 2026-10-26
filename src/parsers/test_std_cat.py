from pathlib import Path
from parsers.word_table_parser import parse_word_tables


def print_record(r):
    print("=" * 100)
    print(f"STT: {r['listing_order']}")
    print(f"TITLE: {r['title']}")
    print("--- CATEGORY ---")
    print("L1:", r["category_level1"])
    print("L2:", r["category_level2"])
    print("L3:", r["category_level3"])
    print("--- STANDARD ---")
    print("RAW:", r["raw_code"])
    print("ORG:", r["org_prefix"])
    print("MAIN:", r["std_main_number"])
    print("PART:", r["std_part"])
    print("YEAR:", r["std_year"])
    print("AMD:", r["amendment"])
    print("VER:", r["version_text"])


if __name__ == "__main__":
    BASE_DIR = Path(__file__).resolve().parents[2]
    word_file = BASE_DIR / "data" / "stdtest-cat.docx"

    records = parse_word_tables(word_file)

    print(f"\nTotal standards parsed: {len(records)}\n")

    # In 15 dòng đầu để kiểm tra
    for r in records[:55]:
        print_record(r)
