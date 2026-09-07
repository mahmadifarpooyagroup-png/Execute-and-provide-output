# Atrin AI Control Plane v2.3 — Project Status

## Current state

The repository is in a hardened RC state. Core persistence, workflow execution, recovery, provider registry, desktop/web adapters, Tauri packaging, frontend integration, and automated validation are implemented.

## Automated validation

The GitHub Actions pipeline validates Python 3.10–3.14, compile/lint/type/security checks, the Python test suite, frontend lint/build, Playwright browser E2E, Tauri Linux checks, and Windows NSIS packaging.

## Hardened paths

- Workflow admission rejects terminal and waiting states from direct execution.
- Workflow pause/resume/cancel calls are checked against the central state machine.
- Expired execution claims are externally verified before reclaim, without holding a SQLite write transaction across network/provider I/O.
- Side-effecting workflow actions default to protected mode in the desktop UI and are explicitly represented in the created step.
- Web profile-aware adapters receive the durable provider-profile fencing token for protected execution.
- Desktop CLI fallback delegates to a real backend operation rather than synthesizing a successful window.
- Tauri startup authenticates an existing local runtime with the per-install runtime token instead of trusting port availability alone.
- Frontend API calls have a bounded timeout and explicit abort handling.

## Remaining environment validation

External provider credentials, real provider endpoints, per-account browser profiles, and clean-machine Windows installation still require deployment-specific acceptance testing. The repository does not invent credentials or claim those external environments are validated by deterministic CI.

Untrusted third-party plugin uploads remain unsupported because worker-process isolation is not equivalent to an OS/container sandbox.
