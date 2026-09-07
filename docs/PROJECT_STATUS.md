# Atrin AI Control Plane — Project Status

## Current status

The `main` branch is the single active development line. Core durability, session leasing, fencing, recovery, authenticated local API, provider adapters, tests, frontend runtime integration, and CI hardening are implemented and continuously checked.

## Verified in CI

- Python 3.12 installation and package installation
- Playwright Chromium installation
- Python syntax compilation
- Python test suite
- Frontend dependency installation
- Frontend lint
- Frontend production build
- Tauri Rust formatting and Linux compilation checks
- Windows Tauri NSIS build gate (environment-dependent)

## Operational APIs

The local FastAPI runtime provides authenticated endpoints for workflow creation/list/detail, step execution, pause/resume/cancel, provider profiles, session acquire/renew/release, recovery listing, and audit listing.

The runtime remains intentionally local-only by default. Persisting a provider profile does not automatically load executable provider code; a provider adapter must be registered in the `WorkflowEngine` runtime.

## Frontend status

The active React application now uses `frontend/src/services/api.ts` and the authenticated runtime API instead of the removed deterministic mock service. The Settings screen provides a local runtime-token entry point.

The UI is an operational foundation, but advanced workflow authoring, live step progress, provider configuration, and full recovery actions still require additional product-level integration work.

## Important security boundaries

- The runtime is local-only by default.
- Provider/session execution can require an exact fencing token and active lease.
- Ambiguous external side effects are not silently retried.
- Web evidence is redacted/bounded before persistence where adapter-level evidence capture supports it.
- Plugins are not a security sandbox; only trusted administrator-controlled plugins should be installed until isolated plugin workers are implemented.
- Windows packaging must be validated on the Windows CI runner and on the target deployment environment before release.
- The local runtime token is stored by the browser/Tauri UI in local storage for convenience; a platform secure-secret store should be used for higher-assurance deployments.

## Known remaining work

- Complete the provider adapter registry and runtime wiring for real external providers.
- Finish workflow controls and live state/action feedback in the React UI.
- Add a platform secure-secret store for desktop credentials/tokens.
- Implement isolated plugin workers/sandboxing before untrusted plugins are allowed.
- Complete environment-specific tests using real provider credentials and authenticated sessions.
- Validate the final Windows installer on a clean Windows machine.

## Release position

The core test suite and frontend build are passing in CI on the current development line. This repository should be treated as a hardened development/RC baseline, not as a blanket claim of production readiness for arbitrary external providers, untrusted plugins, or every Windows deployment environment.
