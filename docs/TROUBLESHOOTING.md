# Troubleshooting

## Runtime does not start

Use the factory form from the repository root:

```bash
uvicorn atrin_core.runtime:create_app --factory --host 127.0.0.1 --port 8765
```

Confirm Python dependencies are installed and port 8765 is free. `GET /health` is the first health check.

## The UI reports an authentication error

Open Settings and enter the local runtime token from `.atrin_data/runtime_secret.token`. The active UI stores the token only in session-scoped browser storage. Never place it in a URL or source file.

## Provider catalog is empty

Set `ATRIN_PROVIDERS_JSON` to a JSON array or `ATRIN_PROVIDERS_FILE` to a UTF-8 JSON file. The provider must reference a registered adapter ID such as `web`, `api`, `chat-completions`, `mcp`, `a2a`, or `acp`.

## A provider profile cannot be created

Confirm the `provider_id` exists in the provider catalog, the profile ID is unique, and the request is authenticated. Duplicate profile IDs return a conflict instead of overwriting an existing profile silently.

## A workflow cannot execute

Confirm that its provider profile belongs to the configured provider, the provider adapter is enabled, the account/session is available, and the step has the required capability. Inspect `/api/v1/workflows/{workflow_id}` and `/api/v1/audit` for durable state and events.

## A workflow is waiting for recovery

Use `/api/v1/recovery` or the Recovery page to identify the reason: authentication, network, provider availability, human interaction, or approval. Resolve the external condition and resume. Do not blindly replay a completed side effect.

## Browser provider is stuck

Confirm the configured `start_url` and selectors under `metadata.web`. Use a dedicated persistent `profile_path` for each account. A browser profile contains sensitive session state and must not be shared between unrelated providers or accounts.

## CI fails

Run locally:

```bash
pytest -q
cd frontend && npm run lint && npm run build
```

For Browser E2E, install Chromium with `python -m playwright install --with-deps chromium` and run `pytest -q tests/test_ui_browser_e2e.py`. The test uses only a deterministic local provider.

## Windows installer issues

Use the generated NSIS artifact from the Windows CI job. Before production release, install and launch the installer on a clean target machine with WebView2 available and verify that the managed local runtime reaches `/health`.
