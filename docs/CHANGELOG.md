# Atrin AI Control Plane v2.3 Changelog

## Table of Contents

- [v2.3.0](#v230)
- [Breaking Changes](#breaking-changes)
- [Known Issues](#known-issues)

## v2.3.0

Atrin v2.3 completes the 13-phase implementation described by the master specification.

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

## Breaking Changes

- The runtime is local-only by default and binds to `127.0.0.1`; deployments must deliberately design any remote access boundary.
- `/api/v1/status` requires the `X-Atrin-Token` header.
- There is no supported public REST CRUD contract yet for workflows, sessions, providers, or recovery; integrations must use the Python core APIs until those routes are added.
- The React UI is a scaffold backed by mock data and should not be treated as a live operational console.
- Windows packaging requires a Windows build environment with Rust stable, WebView2, and the required native build tools.

## Known Issues

- The frontend does not yet call the Python runtime; dashboard, provider, workflow, recovery, and settings data are deterministic mock values.
- The first-run wizard is navigable, but its Continue setup action is not wired to persistence.
- UI smoke tests validate route declarations and bindings at source level, not full browser interaction.
- External provider and real API calls remain stubbed for deterministic tests.
- The repository does not ship a Dockerfile, compose file, production service unit, or reverse-proxy configuration.
- The Windows installer has not been built in the current Linux/Codespace environment.

For installation and operational work, see [INSTALLATION.md](INSTALLATION.md) and [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
