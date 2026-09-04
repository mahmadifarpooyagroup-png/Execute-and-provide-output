# Atrin AI Control Plane v2.3 API Reference

## Table of Contents

- [API Status](#api-status)
- [Base URL](#base-url)
- [Authentication](#authentication)
- [Endpoints](#endpoints)
- [Request and Response Examples](#request-and-response-examples)
- [Error Codes](#error-codes)
- [Core Service APIs](#core-service-apis)

## API Status

The shipped FastAPI application currently exposes two HTTP endpoints. Workflow, session, provider, recovery, and settings screens exist in the frontend, but CRUD REST endpoints for those resources are not implemented in v2.3. The frontend currently reads deterministic mock data from `frontend/src/services/mockApi.ts`.

## Base URL

The local runtime defaults to `http://127.0.0.1:8765`. Start it with:

```bash
uvicorn atrin_core.runtime:app --host 127.0.0.1 --port 8765
```

The service intentionally binds to loopback by default.

## Authentication

`GET /health` is public. `GET /api/v1/status` requires the local runtime token in the `X-Atrin-Token` header. The token is generated and stored at `.atrin_data/runtime_secret.token` on first use by `LocalSecurityManager`.

```bash
TOKEN=$(cat .atrin_data/runtime_secret.token)
curl -H "X-Atrin-Token: $TOKEN" http://127.0.0.1:8765/api/v1/status
```

Do not place the token in source control, URLs, browser bookmarks, or support logs.

## Endpoints

### Health check

`GET /health`

No authentication required. Returns service liveness.

Response `200`:

```json
{"status":"healthy","service":"atrin-control-plane"}
```

### Runtime status

`GET /api/v1/status`

Requires `X-Atrin-Token`. Returns authenticated local runtime status.

Response `200`:

```json
{"status":"operational","message":"Local runtime is secure and running"}
```

Response `401`:

```json
{"detail":"Invalid or missing Atrin runtime token"}
```

### Workflow management

No REST endpoints are currently implemented. Workflow creation, state inspection, step execution, pause, resume, checkpoints, and idempotency are provided by the Python `WorkflowEngine` and `RecoveryEngine` classes. See [Core Service APIs](#core-service-apis).

### Session management

No REST endpoints are currently implemented. Provider profile and session operations are provided by `SessionManager`.

### Provider management

No REST endpoints are currently implemented. Provider definitions and adapter registration are handled by the core provider and adapter interfaces.

## Request and Response Examples

Check liveness:

```bash
curl -i http://127.0.0.1:8765/health
```

Check authenticated status with Python:

```python
from pathlib import Path
import httpx

token = Path('.atrin_data/runtime_secret.token').read_text().strip()
response = httpx.get(
    'http://127.0.0.1:8765/api/v1/status',
    headers={'X-Atrin-Token': token},
)
response.raise_for_status()
print(response.json())
```

## Error Codes

| HTTP status | Meaning | Applies to |
|---|---|---|
| `200 OK` | Request completed successfully. | `/health`, `/api/v1/status` |
| `401 Unauthorized` | Token is missing or invalid. | `/api/v1/status` |
| `404 Not Found` | Route is not registered or resource is absent. | Any unsupported route or future resource route |
| `500 Internal Server Error` | Unexpected server-side exception. | Runtime and future endpoints |

The API does not currently define a versioned error schema beyond FastAPI's `detail` response.

## Core Service APIs

Developers integrating directly with the Python core should use the tested service classes rather than assuming unavailable HTTP routes:

- `AtrinDatabase(db_path)` initializes SQLite schema and WAL mode.
- `SessionManager` creates provider profiles, acquires/releases profile locks, and manages session state.
- `WorkflowEngine.create_workflow(goal, plan)` persists a workflow, tasks, steps, and an initial checkpoint.
- `WorkflowEngine.get_workflow_state(workflow_id)` reads durable workflow state.
- `WorkflowEngine.execute_step(workflow_id, step_id)` dispatches a step through its registered adapter.
- `WorkflowEngine.pause_workflow(...)` and `resume_workflow(...)` control recoverable execution.
- `RecoveryEngine` persists and resumes checkpoints for network and authentication interruptions.
- `LocalSecurityManager` creates and validates the local runtime token.

These are Python APIs, not REST endpoints, and their signatures should be checked in the source before integration. Provider-specific behavior must remain behind adapter contracts.
