# Atrin AI Control Plane — Project Status

## Current status

The `main` branch is the single active development line. Core durability, session leasing, fencing, recovery, authenticated local API, provider adapters, tests, and CI hardening are implemented and continuously checked.

## Verified in CI

- Python 3.12 installation and package installation
- Playwright Chromium installation
- Python syntax compilation
- Python test suite
- Frontend dependency installation
- Frontend lint
- Frontend production build

## Operational APIs

The local FastAPI runtime provides authenticated endpoints for workflow creation/list/detail, step execution, pause/resume/cancel, provider profiles, session acquire/renew/release, recovery listing, and audit listing.

## Important security boundaries

- The runtime is local-only by default.
- Provider/session execution can require an exact fencing token and active lease.
- Ambiguous external side effects are not silently retried.
- Web evidence is redacted and bounded before persistence.
- Plugins are not a security sandbox; only trusted administrator-controlled plugins should be installed until isolated plugin workers are implemented.
- The Windows desktop package still requires dedicated Windows build validation.

## Remaining product integration

The React UI still contains deterministic mock service paths and must be migrated to the authenticated runtime API for live operational use. Real external-provider credentials/sessions and Windows packaging require environment-specific integration testing.
