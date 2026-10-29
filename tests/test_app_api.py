"""Contract tests for the parser HTTP API (src/app/main.py)."""

import pytest
from fastapi.testclient import TestClient

from src.app import main as app_module
from src.app.main import app


@pytest.fixture(autouse=True)
def _reset_api_key(monkeypatch):
    """Keep tests deterministic even if the local .env has a real key."""
    monkeypatch.setattr(app_module, "PARSER_API_KEY", "")


@pytest.fixture()
def client():
    return TestClient(app)


def test_health(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == app.version
    assert isinstance(body["ai_available"], bool)


def test_parse_code(client):
    response = client.post(
        "/api/v1/parse/code",
        json={"code": "TCVN 13566-1,2,3:2022", "use_ai_fallback": False},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["organization"] == "TCVN"
    assert body["main_number"] == "13566"
    assert body["year"] == 2022
    assert body["parts"] == "1-2-3"
    assert body["corrected_code"] == "TCVN 13566-1-2-3:2022"
    assert body["verified"] is True


def test_parse_text_expands_ranges_and_lists(client):
    response = client.post(
        "/api/v1/parse/text",
        json={
            "text": "TCVN 13566-1,2,3:2022 và ISO 9001:2015",
            "use_ai_fallback": False,
        },
    )
    assert response.status_code == 200
    body = response.json()
    codes = {record["corrected_code"] for record in body["records"]}
    assert codes == {
        "TCVN 13566-1:2022",
        "TCVN 13566-2:2022",
        "TCVN 13566-3:2022",
        "ISO 9001:2015",
    }
    assert body["count"] == 4


def test_parse_text_rejects_blank_input(client):
    response = client.post("/api/v1/parse/text", json={"text": "   "})
    assert response.status_code == 422


def test_legacy_paths_still_work(client):
    response = client.post(
        "/api/parse/text",
        json={"text": "TCVN 1234:2020", "use_ai_fallback": False},
    )
    assert response.status_code == 200
    assert response.json()["count"] == 1


def test_api_key_is_enforced_when_configured(client, monkeypatch):
    monkeypatch.setattr(app_module, "PARSER_API_KEY", "secret")

    assert client.post("/api/v1/parse/text", json={"text": "TCVN 1234:2020"}).status_code == 401

    authorized = client.post(
        "/api/v1/parse/text",
        json={"text": "TCVN 1234:2020"},
        headers={"X-API-Key": "secret"},
    )
    assert authorized.status_code == 200

    # Health stays public.
    assert client.get("/api/v1/health").status_code == 200


def test_parse_files_rejects_unsupported_extension(client):
    response = client.post(
        "/api/v1/parse/files",
        files=[("files", ("notes.txt", b"TCVN 1234:2020", "text/plain"))],
    )
    assert response.status_code == 415


def test_parse_files_reads_xlsx(client, tmp_path):
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["TT", "Tên tiêu chuẩn", "Mã tiêu chuẩn"])
    sheet.append(["1", "Tiêu chuẩn thử", "TCVN 1234:2020"])
    path = tmp_path / "catalog.xlsx"
    workbook.save(path)

    response = client.post(
        "/api/v1/parse/files",
        files=[
            (
                "files",
                (
                    "catalog.xlsx",
                    path.read_bytes(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ),
            )
        ],
        data={"use_ai_fallback": "false"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["files"] == [{"filename": "catalog.xlsx", "count": 1}]
    record = body["records"][0]
    assert record["corrected_code"] == "TCVN 1234:2020"
    assert record["standard_name"] == "Tiêu chuẩn thử"
    assert record["stt"] == "1"
    assert record["source_file"] == "catalog.xlsx"
    assert record["verified"] is True


def test_openapi_schema_uses_versioned_paths_only(client):
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    assert "/api/v1/parse/code" in paths
    assert "/api/v1/parse/text" in paths
    assert "/api/v1/parse/files" in paths
    assert "/api/parse/text" not in paths
