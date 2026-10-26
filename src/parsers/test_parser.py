import sys, os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from parsers.std_code_parser import parse_standard_code

samples = [
    "IEC 62368-1:2020+AMD1:2021",
    "IEEE 1588:2008 (Version 2)",
    "DIN VDE 0816-2:1988",
    "3GPP TS 33.501 (Rel-18):2025",
]

for s in samples:
    print(parse_standard_code(s))
