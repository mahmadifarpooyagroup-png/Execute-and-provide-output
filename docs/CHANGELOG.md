# Atrin AI Control Plane v2.3 Changelog

## Table of Contents

- [v2.3.0](#v230)
- [Breaking Changes](#breaking-changes)
- [Resolved Issues](#resolved-issues)
- [Known Issues](#known-issues)

## v2.3.0

Atrin v2.3 completes the implementation described by the master specification.

### Completed phases

1. Core project foundation and architecture.
2. Protocol and adapter interfaces.
3. Database and persistence layer.
4. Provider registration and session management.
5. Workflow and task modeling.
6. Workflow execution engine.
7. Recovery and checkpoint orchestration.
8. Security and runtime guardrails.
9. Desktop integration and Tauri UI shell.
10. Provider adapter hardening.
11. Desktop UI foundation.
12. Windows packaging foundation.
13. End-to-end verification and acceptance testing.

### New features

- Vendor-neutral provider registry and capability model.
- Adapter contracts for web, desktop, API, MCP, A2A, and ACP integrations.
- SQLite persistence with WAL mode.
- Provider profile and session lifecycle management with fencing tokens.
- Multi-step workflows with durable tasks and steps.
- Checkpoint storage and recovery for transient failures.
- Idempotency ledger to prevent duplicate confirmed side effects.
- Audit logging for workflow and lifecycle events.
- Operational REST API for workflows, sessions/profiles, recovery, and audit queries.
- Recovery Center and operational UI routes.
- Tauri 2 Windows packaging configuration with NSIS and WebView2 offline installer support.
- Automated core acceptance and UI smoke validation.

### Bug fixes and hardening

- Preserved workflow state independently of external provider session state.
- Distinguished network unavailability from authentication failure.
- Added recoverable waiting states for authentication, network, provider, and human interaction conditions.
- Added local runtime token validation for the authenticated status endpoint.
- Corrected frontend route and navigation declarations for the desktop UI shell.
- Added idempotent database schema initialization and WAL configuration.
- Bound recovery verification to the durable provider adapter rather than using a generic verifier.
- Added provider-scoped idempotency ownership checks and expired-claim verification before reclaim.
- Added checkpoint revision checks to prevent lost updates during concurrent recovery.
- Added explicit verifier-confirmation audit events and ambiguous-action pause handling.
- Wired first-run wizard progression, completion persistence, and root-route redirection.

## Breaking Changes

- The runtime is local-only by default and binds to `127.0.0.1`; deployments must deliberately design any remote access boundary.
- `/api/v1/status` requires the `X-Atrin-Token` header.
- Operational routes are intentionally local and must be protected before any remote exposure.
- Windows packaging requires a Windows build environment with Rust stable, WebView2, and the required native build tools.

## Resolved Issues

- ~~The first-run wizard was navigable, but its Continue setup action was not wired to persistence.~~
  **Fixed:** The wizard now advances through all four stages, persists completion to `localStorage`, and redirects the user to the dashboard on completion. The root route sends incomplete users to `/wizard` and returning users to `/dashboard`.
- ~~The Windows installer had not been built in the current Linux/Codespace environment.~~
  **Fixed:** CI builds the NSIS installer on a dedicated Windows runner and uploads the installer artifact.

## Known Issues

- External provider and real API calls still require deployment-specific provider credentials, endpoints, browser profiles, and environment validation; CI uses deterministic providers for safe automated verification.
- Source-level UI smoke tests complement the real Playwright browser journey; neither validates every arbitrary production provider or account configuration.
- The repository does not ship a Dockerfile, compose file, production service unit, or reverse-proxy configuration.
- Plugin worker isolation is not a full OS/container sandbox; untrusted third-party plugin uploads remain unsupported.
- Browser profiles are sensitive credential stores and must be isolated per provider/account.

For installation and operational work, see [INSTALLATION.md](INSTALLATION.md) and [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
