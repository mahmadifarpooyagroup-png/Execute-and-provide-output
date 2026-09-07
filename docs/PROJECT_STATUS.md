# Atrin AI Control Plane — Project Status

## Current status

The `main` branch is the single active development line. Core durability, session leasing, fencing, recovery, authenticated local API, provider adapters, plugin persistence/isolation, frontend runtime integration, and CI hardening are implemented and continuously checked.

## Verified in CI

The latest successful CI run on the previous `main` head verified:

- Python 3.10, 3.11, 3.12, 3.13, and 3.14 installation and test execution
- Playwright Chromium installation
- Python syntax compilation
- Ruff lint, mypy type checking, and Bandit security scanning
- Python test suite (69 tests in the Python 3.13 job)
- Frontend dependency installation, lint, and production build
- Tauri Rust formatting and Linux compilation checks
- Windows Tauri NSIS packaging

## Operational APIs

The local FastAPI runtime provides authenticated endpoints for workflow creation/list/detail, step execution, pause/resume/cancel, provider profiles, session acquire/renew/release, recovery listing, and audit listing.

The runtime remains intentionally local-only by default. Persisting a provider profile does not automatically load executable provider code; a provider adapter must be registered in the `WorkflowEngine` runtime.

## Frontend status

The active React application uses `frontend/src/services/api.ts` and the authenticated runtime API. Runtime/provider/workflow/recovery/audit reads and workflow control actions are routed through the local API rather than the removed deterministic mock service. The Settings screen provides a local runtime-token entry point using session-scoped browser storage.

The UI is an operational foundation, but advanced workflow authoring, live step progress, richer provider configuration, and full recovery UX still require additional product-level integration work.

## Important security boundaries

- The runtime is local-only by default.
- Provider/session execution can require an exact fencing token and active lease.
- Ambiguous external side effects are not silently retried.
- Web evidence is redacted/bounded before persistence where adapter-level evidence capture supports it.
- Plugins execute in dedicated spawned worker processes, have persistent registry metadata with file-hash verification, and are not equivalent to a full OS/container sandbox. Only administrator-controlled plugins should be treated as trusted until stronger OS-level isolation is introduced.
- The local runtime token is generated and protected by the backend runtime; the frontend keeps the token only for the current browser/Tauri session and does not persist it in localStorage.
- Windows packaging must be validated on the Windows CI runner and on the target deployment environment before release.

## Known remaining work

- Complete the provider adapter registry and runtime wiring for real external providers.
- Finish workflow controls and live state/action feedback in the React UI.
- Add a platform secure-secret integration where higher-assurance desktop credential handling is required.
- Add true browser-driven UI E2E coverage for critical user journeys; current UI smoke coverage remains source-level/deterministic.
- Add environment-specific tests using real provider credentials and authenticated sessions.
- Validate the final Windows installer on a clean Windows machine.

## Release position

The core test suite, frontend build, Tauri checks, and Windows packaging gate are passing in CI on the current development line. This repository should be treated as a hardened development/RC baseline, not as a blanket claim of production readiness for arbitrary external providers, untrusted plugins, or every Windows deployment environment.
