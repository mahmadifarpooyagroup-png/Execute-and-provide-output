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

The shipped FastAPI application exposes authenticated local endpoints for workflow creation/list/detail, step execution, pause/resume/cancel, provider profiles, session acquire/renew/release, recovery listing, and audit listing. The React frontend uses the authenticated runtime API; deterministic mock service paths are no longer part of the active application path.

The runtime does not yet auto-register external provider adapters from persisted profiles. A workflow step therefore requires a registered adapter in the `WorkflowEngine` before it can execute.

## Base URL

The local runtime defaults to `http://127.0.0.1:8765`. Start it with:

```bash
uvicorn atrin_core.runtime:app --host 127.0.0.1 --port 8765
```

The service intentionally binds to loopback by default.

## Authentication

`GET /health` is public. All `/api/v1/*` endpoints require the local runtime token in the `X-Atrin-Token` header. The token is generated and stored at `.atrin_data/runtime_secret.token` on first use by `LocalSecurityManager`.

```bash
TOKEN=$(cat .atrin_data/runtime_secret.token)
curl -H "X-Atrin-Token: $TOKEN" http://127.0.0.1:8765/api/v1/status
```

Do not place the token in source control, URLs, browser bookmarks, or support logs.

The desktop UI can store the local runtime token in browser storage through the Settings page. Prefer a local development/test runtime and never reuse a production secret in source-controlled configuration.

## Endpoints

### Health check

`GET /health`

No authentication required. Returns service liveness.

Response `200`:

```json
{"status":"healthy","service":"atrin-control-plane","version":"0.2.0"}
```

### Runtime status

`GET /api/v1/status`

Requires `X-Atrin-Token`. Returns authenticated local runtime status.

### Workflow management

`POST /api/v1/workflows`

Creates a durable workflow from a goal and task/step plan.

`GET /api/v1/workflows`

Lists workflows. Optional query parameter: `state`.

`GET /api/v1/workflows/{workflow_id}`

Returns workflow, tasks, steps, and checkpoint data.

`POST /api/v1/workflows/{workflow_id}/run`

Executes one step by `step_id` through its registered provider adapter.

`POST /api/v1/workflows/{workflow_id}/pause`

Pauses a workflow with a required reason.

`POST /api/v1/workflows/{workflow_id}/resume`

Resumes recoverable workflow execution.

`POST /api/v1/workflows/{workflow_id}/cancel`

Cancels a workflow.

### Provider management

`GET /api/v1/providers`

Lists persisted provider profiles.

`POST /api/v1/providers`

Creates a provider profile.

### Session management

`GET /api/v1/sessions`

Lists session/lease records.

`POST /api/v1/sessions/{profile_id}/acquire`

Acquires or renews a lease for a workflow and returns the current fencing token.

`POST /api/v1/sessions/{profile_id}/renew`

Renews a live lease when workflow owner and fencing token match.

`POST /api/v1/sessions/{profile_id}/release`

Releases a lease when workflow owner and fencing token match.

### Recovery

`GET /api/v1/recovery`

Lists workflows currently waiting for authentication, network, provider, human interaction/approval, or recovery.

### Audit

`GET /api/v1/audit`

Lists the most recent audit events. Optional query parameter: `workflow_id`; optional `limit` defaults to 100 and is capped at 1000.

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

Create a workflow:

```bash
curl -X POST http://127.0.0.1:8765/api/v1/workflows \
  -H "Content-Type: application/json" \
  -H "X-Atrin-Token: $TOKEN" \
  -d '{"goal":"example","plan":[]}'
```

## Error Codes

| HTTP status | Meaning | Applies to |
|---|---|---|
| `200 OK` | Request completed successfully. | Authenticated and public endpoints |
| `201 Created` | Resource was created. | Workflow and provider creation |
| `401 Unauthorized` | Token is missing or invalid. | Protected `/api/v1/*` endpoints |
| `404 Not Found` | Resource does not exist. | Workflow, step, or provider/session routes |
| `409 Conflict` | Execution/session conflict, stale lease, or another recoverability constraint. | Workflow run/resume and session operations |
| `500 Internal Server Error` | Unexpected server-side exception. | Runtime and future endpoints |

The API currently uses FastAPI's `detail` error shape rather than a separate versioned error envelope.

## Core Service APIs

Developers integrating directly with the Python core can use:

- `AtrinDatabase(db_path)` for SQLite initialization, safety pragmas, and forward migrations.
- `SessionManager` for provider profiles, leases, and fencing.
- `WorkflowEngine.create_workflow(goal, plan)` for durable workflow creation.
- `WorkflowEngine.get_workflow_state(workflow_id)` for durable state reads.
- `WorkflowEngine.execute_step(workflow_id, step_id)` for adapter-backed execution.
- `WorkflowEngine.pause_workflow(...)` and `resume_workflow(...)` for recoverable execution.
- `RecoveryEngine` for checkpoint-based recovery.
- `LocalSecurityManager` for local runtime token creation and validation.

Provider-specific behavior must remain behind adapter contracts. Persisting a provider profile does not by itself instantiate an external adapter; runtime wiring must supply the adapter implementation appropriate for that provider.
