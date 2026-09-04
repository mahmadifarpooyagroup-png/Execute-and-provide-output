# Atrin AI Control Plane v2.3 Troubleshooting

## Table of Contents

- [Diagnostic Tools](#diagnostic-tools)
- [Common Error Messages](#common-error-messages)
- [Step-by-Step Solutions](#step-by-step-solutions)
- [Getting Help](#getting-help)

## Diagnostic Tools

### Collect logs

Run the backend in the foreground to capture Uvicorn output:

```bash
uvicorn atrin_core.runtime:app --host 127.0.0.1 --port 8765 2>&1 | tee atrin-runtime.log
```

For a support bundle, include the command output, OS and Python/Node versions, the failing workflow ID, and relevant timestamps. Remove tokens, cookies, authorization headers, personal data, and provider payloads first.

### System health checks

```bash
python --version
node --version
npm --version
curl -i http://127.0.0.1:8765/health
ss -ltnp | grep 8765
```

On Windows use `netstat -ano | findstr :8765` instead of `ss`.

### Database integrity checks

Stop writes to the database, then run:

```bash
sqlite3 .atrin_data/atrin.db 'PRAGMA integrity_check;'
sqlite3 .atrin_data/atrin.db 'PRAGMA journal_mode;'
sqlite3 .atrin_data/atrin.db '.tables'
```

Healthy output includes `ok` for the integrity check and `wal` for the journal mode. Back up the database before repair or migration work.

## Common Error Messages

| Message | Meaning | First action |
|---|---|---|
| `Invalid or missing Atrin runtime token` | `X-Atrin-Token` is absent or does not match the local token file. | Read the token from the protected token file and retry. |
| `Address already in use` | Port 8765 is occupied. | Find the process and choose another port or stop the old runtime. |
| `Workflow not found: ...` | The requested ID is not in the selected database. | Check the database path and workflow ID. |
| `No adapter registered for provider: ...` | The workflow references a provider without a registered adapter. | Register a compatible adapter or correct the step's provider ID. |
| `provider authentication challenge detected` | The adapter detected that manual authentication is required. | Authenticate, then resume from the checkpoint. |
| `ModuleNotFoundError` | The active Python environment lacks a dependency or the local package. | Activate `.venv` and rerun `pip install -e '.[dev]'`. |
| `Failed to fetch` | The browser cannot reach the frontend/backend URL. | Check both dev servers, URL, port, and browser console. |

## Step-by-Step Solutions

### Installation failures

1. Confirm Python is 3.10+ and Node.js is 18+.
2. Activate the intended virtual environment.
3. Upgrade pip and install the editable package again:

```bash
python -m pip install --upgrade pip
pip install -e '.[dev]'
```

4. From `frontend`, remove and reinstall dependencies only if the npm error points to a corrupted install:

```bash
rm -rf node_modules
npm install
```

On Windows, use `Remove-Item -Recurse -Force node_modules`.

### Database connection errors

1. Confirm the parent directory is writable.
2. Confirm no second process is using the same SQLite file in an unsafe way.
3. Run the integrity checks above.
4. Verify that the application and diagnostic command use the same absolute database path.
5. Restore the latest known-good backup if integrity fails; do not delete the database before preserving it for investigation.

### Authentication issues

1. Confirm the `X-Atrin-Token` header is present for `/api/v1/status`.
2. Read the token from `.atrin_data/runtime_secret.token` using an account permitted to access the file.
3. Check file ownership and permissions. On Linux, the generated token is restricted to mode `0600`.
4. For a provider authentication challenge, re-authenticate in the provider interface and resume the workflow. Do not classify a DNS or timeout error as an authentication error.

Example:

```bash
TOKEN=$(cat .atrin_data/runtime_secret.token)
curl -H "X-Atrin-Token: $TOKEN" http://127.0.0.1:8765/api/v1/status
```

### Network timeouts

1. Check local DNS and proxy settings.
2. Confirm the provider endpoint is reachable from the same machine or container.
3. Check system clock and TLS certificate validity.
4. Review firewall rules and browser profile connectivity.
5. Let Recovery preserve the checkpoint and retry after the dependency is healthy.

### Workflow execution failures

1. Record the workflow ID, task, step, provider ID, and current state.
2. Inspect the latest checkpoint and audit event.
3. Confirm the provider adapter is registered and capability-compatible.
4. Check whether the failure is a provider, network, authentication, or human-approval wait.
5. Resume from the checkpoint only after the cause is corrected. If the action may have succeeded remotely, verify evidence before retrying.

### UI rendering problems

1. Confirm `npm run dev` is still running and use its exact URL.
2. Run `npm run lint` and `npm run build` from `frontend`.
3. Inspect browser console errors and failed network requests.
4. Confirm the route is one of `/`, `/dashboard`, `/providers`, `/workflows`, `/recovery`, `/settings`, `/wizard`, or `/first-run`.
5. Remember that v2.3 UI data is mock-backed; a visible screen does not prove backend connectivity.

## Getting Help

Before opening a request, run the health, version, test, and database checks above and redact sensitive information.

- **GitHub Issues:** [open an issue in the repository](https://github.com/mahmadifarpooyagroup-png/Execute-and-provide-output/issues) with reproduction steps, expected and actual behavior, environment versions, and sanitized logs.
- **Community forums:** Use the project's GitHub Discussions or the community channel designated by your organization when available.
- **Support contacts:** For an organization-managed deployment, contact the Atrin administrator or internal platform support team. No public support mailbox is configured in this repository.
