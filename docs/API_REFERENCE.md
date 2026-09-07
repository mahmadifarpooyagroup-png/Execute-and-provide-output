# Atrin AI Control Plane v2.3 API Reference

## Table of Contents

- [API Status](#api-status)
- [Base URL](#base-url)
- [Authentication](#authentication)
- [Provider Registry](#provider-registry)
- [Endpoints](#endpoints)
- [Request and Response Examples](#request-and-response-examples)
- [Error Codes](#error-codes)
- [Core Service APIs](#core-service-apis)

## API Status

The shipped FastAPI application exposes authenticated local endpoints for provider catalog discovery, provider profiles, workflow creation/list/detail, step execution, pause/resume/cancel, session acquire/renew/release, recovery listing, and audit listing. The React frontend uses the same authenticated runtime API; deterministic mock service paths are no longer part of the active application path.

The runtime builds provider adapters automatically from the vendor-neutral registry. Provider-specific behavior remains outside the workflow engine.

## Base URL

The local runtime defaults to `http://127.0.0.1:8765`. Start it with:

```bash
uvicorn atrin_core.runtime:create_app --factory --host 127.0.0.1 --port 8765
```

The service intentionally binds to loopback by default.

## Authentication

`GET /health` is public. All `/api/v1/*` endpoints require the local runtime token in the `X-Atrin-Token` header. The token is generated and stored at `.atrin_data/runtime_secret.token` on first use by `LocalSecurityManager`.

```bash
TOKEN=$(cat .atrin_data/runtime_secret.token)
curl -H "X-Atrin-Token: $TOKEN" http://127.0.0.1:8765/api/v1/status
```

Do not place the token in source control, URLs, browser bookmarks, or support logs. The desktop UI stores the token only for the current browser/Tauri session through `sessionStorage`.

## Provider Registry

Providers are configured through `ATRIN_PROVIDERS_JSON` or `ATRIN_PROVIDERS_FILE`. `ATRIN_PROVIDERS_JSON` must contain a JSON array; `ATRIN_PROVIDERS_FILE` points to a UTF-8 JSON file capped at 1 MiB. Secrets should be supplied through environment variables referenced by the provider configuration.

Built-in adapter IDs:

- `web` / `generic-web`: configurable browser interaction strategy.
- `api` / `chat-completions`: generic chat-completions-style HTTP adapter.
- `mcp`: MCP server adapter.
- `a2a`: A2A JSON-RPC task adapter.
- `acp`: ACP session adapter.

Example:

```json
[
  {
    "id": "my-api",
    "name": "My API",
    "adapter_id": "chat-completions",
    "connection_kind": "API",
    "endpoint": "https://example.invalid/v1",
    "metadata": {
      "api": {
        "model": "my-model",
        "api_key_env": "MY_API_KEY"
      },
      "capabilities": ["chat"]
    }
  }
]
```

Web configuration lives under `metadata.web`, for example `start_url`, `composer_selector`, `send_selector`, `response_selector`, `login_selector`, `challenge_selector`, `completion_selector`, `verification_selector`, and optional `profile_path` for a persistent browser profile.

Use `GET /api/v1/provider-catalog` to inspect the configured provider/adapter catalog before creating profiles.

## Endpoints

### Health check

`GET /health`

No authentication required. Returns service liveness.

Response `200`:

```json
{"status":"healthy","service":"atrin-control-plane","version":"0.3.0"}
```

### Runtime status

`GET /api/v1/status`

Requires `X-Atrin-Token`. Returns authenticated local runtime status.

### Provider catalog

`GET /api/v1/provider-catalog`

Requires `X-Atrin-Token`. Returns the configured provider adapters and capabilities.

### Workflow management

`POST /api/v1/workflows`

Creates a durable workflow from a goal and task/step plan.

`GET /api/v1/workflows`

Lists workflows. Optional query parameter: `state`; pagination uses `limit` and `offset`.

`GET /api/v1/workflows/{workflow_id}`

Returns workflow, tasks, steps, and checkpoint data.

`POST /api/v1/workflows/{workflow_id}/run`

Executes one step by `step_id` through its configured provider adapter.

`POST /api/v1/workflows/{workflow_id}/pause`

Pauses a workflow with a required reason.

`POST /api/v1/workflows/{workflow_id}/resume`

Resumes recoverable workflow execution.

`POST /api/v1/workflows/{workflow_id}/cancel`

Cancels a workflow. If an external provider cannot confirm cancellation, the workflow remains in provider recovery rather than being falsely marked cancelled.

### Provider management

`GET /api/v1/providers`

Lists persisted provider profiles.

`POST /api/v1/providers`

Creates a provider profile for a configured provider.

### Session management

`GET /api/v1/sessions`

Lists session/lease records.

`POST /api/v1/sessions/{profile_id}/acquire`

Acquires a lease for a workflow and returns the current fencing token.

`POST /api/v1/sessions/{profile_id}/renew`

Renews a live lease when workflow owner and fencing token match.

`POST /api/v1/sessions/{profile_id}/release`

Releases a lease when workflow owner and fencing token match.

### Recovery

`GET /api/v1/recovery`

Lists workflows currently waiting for authentication, network, provider, human interaction/approval, or recovery.

### Audit

`GET /api/v1/audit`

Lists recent audit events. Optional `workflow_id`; `limit` defaults to 100 and is capped at 1000.

`GET /api/v1/audit/verify`

Validates the audit hash chain.

## Request and Response Examples

Check liveness:

```bash
curl -i http://127.0.0.1:8765/health
```

Check authenticated status:

```bash
curl -H "X-Atrin-Token: $TOKEN" http://127.0.0.1:8765/api/v1/status
```

Inspect configured providers:

```bash
curl -H "X-Atrin-Token: $TOKEN" http://127.0.0.1:8765/api/v1/provider-catalog
```

Create a workflow:

```bash
curl -X POST http://127.0.0.1:8765/api/v1/workflows \
  -H "Content-Type: application/json" \
  -H "X-Atrin-Token: $TOKEN" \
  -H "Idempotency-Key: example-request-1" \
  -d '{"goal":"example","plan":[]}'
```

Create a provider profile:

```bash
curl -X POST http://127.0.0.1:8765/api/v1/providers \
  -H "Content-Type: application/json" \
  -H "X-Atrin-Token: $TOKEN" \
  -d '{"profile_id":"my-profile","provider_id":"my-api","account_id":"account-1","name":"My API account"}'
```

## Error Codes

| HTTP status | Meaning | Applies to |
|---|---|---|
| `200 OK` | Request completed successfully. | Authenticated and public endpoints |
| `201 Created` | Resource was created. | Workflow and provider creation |
| `401 Unauthorized` | Token is missing or invalid. | Protected `/api/v1/*` endpoints |
| `404 Not Found` | Resource does not exist. | Workflow, step, provider/session routes |
| `409 Conflict` | Execution/session conflict, stale lease, duplicate provider profile, or another safety constraint. | Workflow, provider, and session operations |
| `422 Unprocessable Entity` | Request or provider configuration failed validation. | Create/configuration endpoints |
| `500 Internal Server Error` | Unexpected server-side exception. | Runtime and future endpoints |

The API currently uses FastAPI's `detail` error shape rather than a separate versioned error envelope.

## Core Service APIs

Developers integrating directly with the Python core can use:

- `AtrinDatabase(db_path)` for SQLite initialization, safety pragmas, and additive migrations.
- `SessionManager` for provider profiles, leases, and fencing.
- `ProviderAdapterRegistry` for configuration-driven provider discovery and adapter construction.
- `WorkflowEngine.create_workflow(goal, plan)` for durable workflow creation.
- `WorkflowEngine.get_workflow_state(workflow_id)` for durable state reads.
- `WorkflowEngine.execute_step(workflow_id, step_id)` for adapter-backed execution.
- `WorkflowEngine.pause_workflow(...)` and `resume_workflow(...)` for recoverable execution.
- `RecoveryEngine` for checkpoint-based recovery.
- `LocalSecurityManager` for local runtime token creation and validation.

Provider-specific behavior must remain behind adapter contracts. Provider profiles persist account context; the registry determines which executable adapter is available for a provider.
