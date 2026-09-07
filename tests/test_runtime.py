import json

from fastapi.testclient import TestClient

from atrin_core.provider_registry import ProviderAdapterRegistry
from atrin_core.runtime import create_app
from atrin_core.security import LocalSecurityManager


def build_client(tmp_path):
    db_path = str(tmp_path / "runtime.db")
    token_path = str(tmp_path / "runtime.token")
    app = create_app(db_path=db_path, token_path=token_path)
    security = LocalSecurityManager(token_file_path=token_path)
    token = security.get_or_create_token()
    return TestClient(app), token


def test_health_endpoint_public(tmp_path):
    client, _ = build_client(tmp_path)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_status_endpoint_requires_auth(tmp_path):
    client, _ = build_client(tmp_path)
    response = client.get("/api/v1/status")
    assert response.status_code == 401


def test_status_endpoint_with_valid_token(tmp_path):
    client, token = build_client(tmp_path)
    response = client.get("/api/v1/status", headers={"X-Atrin-Token": token})
    assert response.status_code == 200
    assert response.json()["status"] == "operational"
    assert response.json()["version"] == "0.3.0"


def test_provider_catalog_exposes_configured_adapters(tmp_path):
    registry = ProviderAdapterRegistry()
    registry.register({
        "id": "demo-api",
        "name": "Demo API",
        "adapter_id": "openai-compatible",
        "endpoint": "http://127.0.0.1:9000/v1",
        "metadata": {
            "api": {"model": "demo-model", "api_key_env": "DEMO_API_KEY"},
            "capabilities": ["chat"],
        },
    })
    db_path = str(tmp_path / "runtime.db")
    token_path = str(tmp_path / "runtime.token")
    app = create_app(db_path=db_path, token_path=token_path, provider_registry=registry)
    token = LocalSecurityManager(token_file_path=token_path).get_or_create_token()
    client = TestClient(app)

    response = client.get("/api/v1/provider-catalog", headers={"X-Atrin-Token": token})
    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == "demo-api"
    assert response.json()["items"][0]["adapter_id"] == "openai-compatible"


def test_idempotent_workflow_creation_and_pagination(tmp_path):
    client, token = build_client(tmp_path)
    headers = {"X-Atrin-Token": token, "Idempotency-Key": "request-1"}
    plan = [{
        "task_id": "task-1",
        "description": "do work",
        "steps": [{
            "step_id": "step-1",
            "action": "noop",
            "provider_id": "provider-1",
            "idempotency_key": "runtime-key-1",
            "side_effecting": False,
        }],
    }]
    first = client.post("/api/v1/workflows", json={"goal": "test", "plan": plan}, headers=headers)
    assert first.status_code == 201
    workflow_id = first.json()["workflow_id"]

    second_headers = {**headers, "Idempotency-Key": "request-1"}
    second = client.post("/api/v1/workflows", json={"goal": "test", "plan": plan}, headers=second_headers)
    assert second.status_code == 201
    assert second.json()["workflow_id"] == workflow_id

    response = client.get("/api/v1/workflows?limit=1&offset=0", headers=headers)
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["workflow_id"] == workflow_id

    detail = client.get(f"/api/v1/workflows/{workflow_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["steps"][0]["side_effecting"] == 0


def test_runtime_workflow_provider_session_and_audit_endpoints(tmp_path):
    client, token = build_client(tmp_path)
    headers = {"X-Atrin-Token": token}

    response = client.post(
        "/api/v1/providers",
        json={"profile_id": "profile-1", "provider_id": "provider-1", "account_id": "account-1", "name": "Provider One"},
        headers=headers,
    )
    assert response.status_code == 201

    plan = [{
        "task_id": "task-1",
        "description": "do work",
        "steps": [{
            "step_id": "step-1",
            "action": "noop",
            "provider_id": "provider-1",
            "idempotency_key": "runtime-key-1",
            "provider_profile_id": "profile-1",
            "side_effecting": False,
        }],
    }]
    response = client.post("/api/v1/workflows", json={"goal": "test", "plan": plan}, headers=headers)
    assert response.status_code == 201
    workflow_id = response.json()["workflow_id"]

    response = client.get("/api/v1/workflows", headers=headers)
    assert response.status_code == 200
    assert response.json()["items"][0]["workflow_id"] == workflow_id

    response = client.post("/api/v1/sessions/profile-1/acquire", json={"workflow_id": workflow_id}, headers=headers)
    assert response.status_code == 200
    fencing_token = response.json()["fencing_token"]

    response = client.post(
        f"/api/v1/workflows/{workflow_id}/pause",
        json={"reason": "network outage"},
        headers=headers,
    )
    assert response.status_code == 200

    response = client.get("/api/v1/recovery", headers=headers)
    assert response.status_code == 200
    assert response.json()["items"][0]["workflow_id"] == workflow_id

    response = client.get(f"/api/v1/audit?workflow_id={workflow_id}", headers=headers)
    assert response.status_code == 200
    assert any(row["event_type"] == "WORKFLOW_CREATED" for row in response.json()["items"])

    response = client.post("/api/v1/sessions/profile-1/renew", json={"workflow_id": workflow_id, "fencing_token": fencing_token}, headers=headers)
    assert response.status_code == 200
    response = client.post("/api/v1/sessions/profile-1/release", json={"workflow_id": workflow_id, "fencing_token": fencing_token}, headers=headers)
    assert response.status_code == 200


def test_runtime_rejects_invalid_token(tmp_path):
    client, _ = build_client(tmp_path)
    response = client.get("/api/v1/workflows", headers={"X-Atrin-Token": "wrong"})
    assert response.status_code == 401


def test_provider_registry_json_round_trip(tmp_path, monkeypatch):
    config = tmp_path / "providers.json"
    config.write_text(json.dumps([{"id": "web", "adapter_id": "generic-web", "endpoint": "data:text/html,<body></body>"}]), encoding="utf-8")
    monkeypatch.setenv("ATRIN_PROVIDERS_FILE", str(config))
    loaded = ProviderAdapterRegistry.from_environment()
    assert loaded.get("web").adapter_id == "generic-web"
