# Full Code Audit Report

Date: 2026-09-05
Scope: Atrin backend, frontend, tests, i18n/RTL, plugin, sync, workflow, execution, persistence, performance, and documentation surfaces.

## Executive Summary

The audit found and fixed the release-blocking defects that were locally verifiable:

- Execution timeouts now terminate the process tree and return an auditable `timed_out` result instead of escaping as an uncaught exception.
- Session fencing-token increments are serialized with `BEGIN IMMEDIATE`; stale-token validation is available to callers.
- Runtime token storage rejects invalid existing tokens and symbolic-link paths, creates tokens atomically with restrictive permissions, and rejects non-string validation input.
- Checkpoint persistence rejects unsupported values and excessive nesting before JSON storage.
- Sync workflow IDs are restricted to safe path components.
- Plugin AST validation blocks additional dynamic execution primitives and cleanup isolates failures while cleaning all plugins.
- Frontend hardcoded visible labels were moved to matching EN and FA translation keys.

## Critical Issues

### C-001: In-process plugins are not a security sandbox
Status: Residual risk, requires deployment policy.

`PluginManager` imports and executes Python modules in the application process. Static import/call checks cannot prevent all arbitrary Python behavior or protect application secrets from a malicious plugin. Plugins must therefore be treated as trusted code. Production guidance: load only signed plugins from an administrator-controlled directory, or execute plugins in an isolated worker/container with a narrow IPC contract. Do not accept untrusted plugin uploads.

### C-002: Full automated test/build execution was unavailable in this environment
Status: Verification blocker, not an application defect.

`pytest` was not installed or available on PATH, and `frontend/node_modules` was absent, so the requested `PYTHONPATH=. pytest -q` and `npm run build` commands could not execute. The report records this rather than claiming a passing release gate.

## High Priority Issues Fixed

### H-001: Timeout contract was unsafe for callers
Fixed in `atrin_core/execution_bus.py` and `tests/test_execution_bus.py`. A timeout now kills the process tree and returns status `timed_out`, exit code `124`, bounded evidence, and a user-safe error message.

### H-002: Fencing token update was not serialized
Fixed in `atrin_core/session_manager.py`. Lock acquisition now uses an immediate SQLite transaction, validates the profile exists, updates the generation atomically, and exposes `validate_fencing_token` for downstream side-effect checks.

### H-003: Token file handling was not fail-closed
Fixed in `atrin_core/security.py`. Existing invalid tokens and symlink paths are rejected; new tokens use exclusive creation and mode `0600`; token comparison uses constant-time comparison and validates input type.

### H-004: Checkpoint payload accepted arbitrary Python objects
Fixed in `atrin_core/recovery_engine.py`. Checkpoints now accept JSON-compatible scalar, mapping, and sequence values only, with a nesting limit.

### H-005: Remote checkpoint IDs could escape a provider path
Fixed in `atrin_core/cloud_sync.py`. Workflow IDs are validated before constructing remote object IDs. AES-GCM uses a 32-byte derived key, random 16-byte salt, random 12-byte nonce, and PBKDF2-HMAC-SHA256.

### H-006: Visible frontend text bypassed i18n
Fixed across `frontend/src/pages/` and both locale files. EN and FA now contain matching keys for the visible page headings, labels, wizard steps, and status text. React text rendering was used; no `dangerouslySetInnerHTML`, `innerHTML`, or equivalent XSS sink was found.

## Medium Priority Findings

- Plugin registry persistence is not integrated with `PluginManager`; registration currently exists only in memory. Add database-backed installation/activation state before relying on plugin lifecycle across restarts.
- `HTTPStorageProvider` creates a new `httpx.AsyncClient` for each operation. Reuse a managed client for high-volume sync workloads and configure explicit connect/read timeouts and retry policy.
- Several backend modules catch broad `Exception`; these should be narrowed and logged without secrets as those paths evolve.
- API authentication headers are not present in the mock frontend service. This is acceptable for the current mock-only UI, but real API integration must centralize authenticated requests and never place bearer tokens in source or mock data.
- Database schema has foreign keys declared but does not enable `PRAGMA foreign_keys = ON` on each connection. Enable it before production data integrity depends on those relationships.
- No migration framework or rollback mechanism is present; schema changes are currently `CREATE TABLE IF NOT EXISTS` only.

## Low Priority Findings

- Public interfaces and models have inconsistent docstring and return-type coverage.
- `Layout.tsx` has a hardcoded English `aria-label` for navigation; localize accessibility labels before release to Persian-speaking users.
- The frontend package has no `test` script, so component test execution is not currently defined.

## Positive Findings

- Database statements observed in the audited backend use parameter binding for runtime values.
- SQLite WAL mode is enabled during initialization and connection creation.
- Process execution uses `create_subprocess_exec` rather than shell interpolation.
- Local network sync validates resolved paths against the configured root.
- AES-GCM authentication protects encrypted checkpoint payloads and plaintext encryption keys are not written to the sync metadata table.
- React renders provider/workflow data as text nodes rather than injecting HTML.
- Language detection persists the selected language through i18next local storage caching, and `Layout` propagates `lang` and `dir` to the document.
- Workflow checkpoint writes and idempotency ledger operations use parameterized SQL and explicit transactions in the audited paths.

## Verification Performed

- Python syntax compilation: `python -m compileall -q atrin_core` succeeded from the repository root.
- Fencing smoke check: current fencing token accepted and stale token rejected.
- Static searches covered shell execution, SQL interpolation, XSS sinks, hardcoded frontend labels, broad exception handling, and TypeScript `any` usage.
- Requested full Python tests: blocked because `pytest` is unavailable.
- Requested frontend build: blocked because `tsc`/`node_modules` are unavailable.

## Release Recommendation

Do not sign off the release until dependencies are installed and the full Python suite plus frontend build pass. Treat the plugin trust boundary as a deployment security requirement, not as solved by AST filtering alone. Enable SQLite foreign keys and add authenticated API plumbing before connecting the mock frontend to production services.
