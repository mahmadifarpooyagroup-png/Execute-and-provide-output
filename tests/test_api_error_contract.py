"""
Tests for the standard API error contract (بند ۲۶ — گزارش قبلی).

Every error response from the runtime API must have the shape:
    {"error": {"code": str, "message": str, "recoverable": bool, ...}}
regardless of whether the raising code used api_error() explicitly or a
legacy HTTPException(detail=<plain string>).
"""
from fastapi.testclient import TestClient

from atrin_core.runtime import create_app
from atrin_core.security import LocalSecurityManager


def build_client(tmp_path):
    db_path = str(tmp_path / "runtime.db")
    token_path = str(tmp_path / "runtime.token")
    app = create_app(db_path=db_path, token_path=token_path)
    security = LocalSecurityManager(token_file_path=token_path)
    token = security.get_or_create_token()
    return TestClient(app), token


def test_structured_error_for_converted_endpoint(tmp_path):
    client, token = build_client(tmp_path)
    headers = {"X-Atrin-Token": token}
    response = client.post(
        "/api/v1/workflows/does-not-exist/run",
        json={"step_id": "step-1"},
        headers=headers,
    )
    assert response.status_code == 404
    body = response.json()
    assert "error" in body
    error = body["error"]
    assert error["code"] == "WORKFLOW_NOT_FOUND"
    assert isinstance(error["message"], str) and error["message"]
    assert error["recoverable"] is False
    assert error["workflow_id"] == "does-not-exist"


def test_structured_error_for_legacy_plain_string_detail(tmp_path):
    client, _ = build_client(tmp_path)
    response = client.get("/api/v1/status")
    assert response.status_code == 401
    body = response.json()
    assert "error" in body
    error = body["error"]
    assert error["code"] == "UNAUTHORIZED"
    assert isinstance(error["message"], str) and error["message"]
    assert error["recoverable"] is True


def test_structured_error_for_unmatched_route(tmp_path):
    client, token = build_client(tmp_path)
    response = client.get("/api/v1/this-route-does-not-exist", headers={"X-Atrin-Token": token})
    assert response.status_code == 404
    body = response.json()
    assert "error" in body
    assert body["error"]["code"] == "NOT_FOUND"


def test_structured_error_for_validation_failure(tmp_path):
    client, token = build_client(tmp_path)
    headers = {"X-Atrin-Token": token}
    response = client.post(
        "/api/v1/workflows/some-id/run",
        json={},
        headers=headers,
    )
    assert response.status_code == 422
    body = response.json()
    assert "error" in body
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "details" in body["error"]


def test_structured_error_includes_recoverable_flag_for_conflict(tmp_path):
    client, token = build_client(tmp_path)
    headers = {"X-Atrin-Token": token}
    response = client.post(
        "/api/v1/providers",
        json={"profile_id": "dup-profile", "provider_id": "prov-x", "account_id": "acct-x", "name": "X"},
        headers=headers,
    )
    assert response.status_code == 201
    response = client.post(
        "/api/v1/providers",
        json={"profile_id": "dup-profile", "provider_id": "prov-x", "account_id": "acct-x", "name": "X"},
        headers=headers,
    )
    assert response.status_code == 409
    body = response.json()
    assert "error" in body
    assert body["error"]["code"] == "CONFLICT"


def test_api_error_helper_builds_expected_shape():
    from atrin_core.api_errors import api_error

    exc = api_error(404, "THING_NOT_FOUND", "The thing was not found", recoverable=False, thing_id="abc")
    assert exc.status_code == 404
    assert exc.detail == {
        "code": "THING_NOT_FOUND",
        "message": "The thing was not found",
        "recoverable": False,
        "thing_id": "abc",
    }


def test_api_error_omits_recoverable_when_not_specified():
    from atrin_core.api_errors import api_error

    exc = api_error(500, "INTERNAL_ERROR", "Something broke")
    assert "recoverable" not in exc.detail
    assert exc.detail["code"] == "INTERNAL_ERROR"
