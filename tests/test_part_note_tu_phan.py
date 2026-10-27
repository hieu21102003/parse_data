"""Tests for a part note written "từ phần X đến Y".

The user's exact failing pair::

    TCVN 1998:2005(từ phần 1 đến 10)   <- did NOT normalise
    TCVN 1998:2005(phần 1 đến 10)      <- normalised to 10 parts

The deterministic parser already understood the "từ phần"
form, but the extractor's _PART_NOTE pattern rejected it, so
clean_code_candidate() stripped the whole parenthetical
before the parser ever saw it and the parts (and, when the
year lived only in the note, the year) were lost. The fix is
in _PART_NOTE only: the part keyword ("phần"/"part") may
appear on either side of the range, after "từ"/"from", and
the separator may be a hyphen as well as "đến"/"tới"/"to".
Endpoints stay 1-3 digits, so a date range such as
"từ 2020 đến 2025" is still not a part note.
"""

try:
    from ingestion.standard_code_extractor import _PART_NOTE
except ModuleNotFoundError:  # pragma: no cover - repo-root PYTHONPATH
    from src.ingestion.standard_code_extractor import _PART_NOTE  # type: ignore

try:
    from pipeline import process_document, process_text
except ModuleNotFoundError:  # pragma: no cover - repo-root PYTHONPATH
    from src.pipeline import process_document, process_text  # type: ignore

FAILING = "TCVN 1998:2005(từ phần 1 đến 10)"
WORKING = "TCVN 1998:2005(phần 1 đến 10)"


def _codes(records):
    return [r["corrected_code"] for r in records]


def test_part_note_pattern_accepts_tu_phan_forms():
    accepted = [
        "từ phần 1 đến 10",
        "từ 1 đến phần 10",
        "từ phần 1 đến phần 10",
        "từ phần 1 đến 10, 2019",
        "từ 1 - 10",
        "từ phần 1 - 10",
        "từ phần 1, 2, 3",
        "từ các phần 1 đến 10",
        "phần 1 đến 10",
        "các phần từ 1 đến 10",
        "từ 1 đến 10",
        "from part 1 to part 10",
    ]
    for note in accepted:
        assert _PART_NOTE.fullmatch(note), note


def test_part_note_pattern_still_rejects_date_ranges_and_bare_numbers():
    rejected = [
        "từ 2020 đến 2025",
        "từ phần 2020 đến 2025",
        "từ 1",
        "1",
    ]
    for note in rejected:
        assert not _PART_NOTE.fullmatch(note), note


def test_tu_phan_form_normalises_like_phan_form():
    expected = [f"TCVN 1998-{part}:2005" for part in range(1, 11)]
    for text in (FAILING, WORKING, "TCVN 1998:2005 (từ phần 1 đến 10)"):
        records = process_text(text, use_ai_fallback=False)
        assert _codes(records) == expected, text
        for record in records:
            assert record["year"] == 2005
            assert record["verified"] is True


def test_tu_phan_keyword_on_either_side_and_hyphen_separator():
    expected = [f"TCVN 1998-{part}:2005" for part in range(1, 11)]
    for text in (
        "TCVN 1998:2005(từ 1 đến phần 10)",
        "TCVN 1998:2005(từ phần 1 đến phần 10)",
        "TCVN 1998:2005(từ 1 - 10)",
        "TCVN 1998:2005(từ phần 1 - 10)",
    ):
        assert _codes(process_text(text, use_ai_fallback=False)) == expected


def test_tu_phan_comma_list_and_year_in_note():
    records = process_text(
        "TCVN 1998:2005(từ phần 1, 2, 3)", use_ai_fallback=False
    )
    assert _codes(records) == ["TCVN 1998-1:2005", "TCVN 1998-2:2005", "TCVN 1998-3:2005"]

    # Year carried only in the note is used; an outside year wins.
    records = process_text(
        "TCVN 1998(từ phần 1 đến 10, 2019)", use_ai_fallback=False
    )
    assert _codes(records) == [f"TCVN 1998-{part}:2019" for part in range(1, 11)]
    records = process_text(
        "TCVN 1998:2005(từ phần 1 đến 10, 2019)", use_ai_fallback=False
    )
    assert _codes(records) == [f"TCVN 1998-{part}:2005" for part in range(1, 11)]


def test_date_range_in_parentheses_is_not_a_part_range():
    records = process_text(
        "TCVN 1998:2005(từ 2020 đến 2025)", use_ai_fallback=False
    )
    assert len(records) == 1
    assert records[0]["corrected_code"] == "TCVN 1998:2005"
    assert records[0]["parts"] is None


def test_process_document_tu_phan_form(tmp_path):
    from docx import Document

    path = tmp_path / "tu_phan.docx"
    doc = Document()
    doc.add_paragraph(f"Áp dụng {FAILING}.")
    doc.save(str(path))

    records = process_document(str(path), use_ai_fallback=False)
    assert _codes(records) == [f"TCVN 1998-{part}:2005" for part in range(1, 11)]
