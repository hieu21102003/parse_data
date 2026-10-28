"""Tests that the combined "BS EN" prefix is kept as written.

The user reported that ``BS EN 13146-3:2019`` came out as
``EN 13146-3:2019`` -- the "BS" was cleared -- while it must be
kept as-is. Root cause: ``ORG_MAP`` mapped ``"BS EN"`` to ``"EN"``,
so the normalized organization (and therefore ``corrected_code``)
dropped the British adoption prefix, even though ``raw_text``
already kept it. "BS EN" is a different designation from a bare
"EN", so the combined prefix is preserved, the same rule the
user's own "TCVN EN" entry in ``ORG_MAP`` states for that prefix.

Guards: a bare ``EN ...`` code must NOT gain a "BS", and a bare
``BS ...`` code must NOT gain an "EN" -- nothing is invented.
"""

try:
    from parsers.std_code_parser import parse_standard_code, normalize_org
except ModuleNotFoundError:  # pragma: no cover - repo-root PYTHONPATH
    from src.parsers.std_code_parser import parse_standard_code, normalize_org  # type: ignore

try:
    from pipeline import process_candidate, process_candidate_expanded, process_document, process_text
except ModuleNotFoundError:  # pragma: no cover - repo-root PYTHONPATH
    from src.pipeline import process_candidate, process_candidate_expanded, process_document, process_text  # type: ignore


def test_parser_preserves_bs_en():
    parsed = parse_standard_code("BS EN 13146-3:2019")
    assert parsed["org_prefix"] == "BS EN"
    assert parsed["org_normalized"] == "BS EN"
    assert parsed["std_main_number"] == "13146"
    assert parsed["std_parts"] == ["3"]
    assert parsed["std_year"] == 2019
    assert parsed["verified"] is True
    assert normalize_org("BS EN") == ("BS EN", 1.0)


def test_candidate_and_text_keep_bs_en():
    record = process_candidate("BS EN 13146-3:2019", use_ai_fallback=False)
    assert record["raw_text"] == "BS EN 13146-3:2019"
    assert record["corrected_code"] == "BS EN 13146-3:2019"
    assert record["organization"] == "BS EN"

    records = process_text("BS EN 13146-3:2019", use_ai_fallback=False)
    assert len(records) == 1
    assert records[0]["corrected_code"] == "BS EN 13146-3:2019"


def test_range_expansion_keeps_bs_en_per_part():
    records = process_candidate_expanded("BS EN 13146-1 đến 10:2019", use_ai_fallback=False)
    assert len(records) == 10
    assert [r["corrected_code"] for r in records] == [
        f"BS EN 13146-{n}:2019" for n in range(1, 11)
    ]
    assert all(r["organization"] == "BS EN" for r in records)


def test_compound_inner_code_keeps_bs_en():
    records = process_text(
        "TCVN 13695-3:2023 (BS EN 13146-3:2019)", use_ai_fallback=False
    )
    by_code = {r["corrected_code"]: r for r in records}
    assert "BS EN 13146-3:2019" in by_code
    assert by_code["BS EN 13146-3:2019"]["year"] == 2019
    assert "EN 13146-3:2019" not in by_code


def test_document_run_keeps_bs_en(tmp_path):
    import pandas as pd

    path = tmp_path / "bs_en.xlsx"
    pd.DataFrame({"Ma": ["TCVN 13695-3:2023 (BS EN 13146-3:2019)"]}).to_excel(
        path, index=False
    )
    records = process_document(str(path), use_ai_fallback=False)
    by_code = {r["corrected_code"]: r for r in records}
    assert "BS EN 13146-3:2019" in by_code
    assert by_code["BS EN 13146-3:2019"]["raw_text"] == "BS EN 13146-3:2019"


def test_bare_en_and_bare_bs_gain_nothing():
    en = process_candidate("EN 13146-3:2019", use_ai_fallback=False)
    assert en["corrected_code"] == "EN 13146-3:2019"
    assert en["organization"] == "EN"

    bs = process_candidate("BS 1234:2019", use_ai_fallback=False)
    assert bs["corrected_code"] == "BS 1234:2019"
    assert bs["organization"] == "BS"
