# E2E Test Report

## Scope
This report covers the end-to-end acceptance and UI smoke checks required by Atrin Spec v2.3 for the Phase 13 verification milestone.

## Scenarios

### 1. Complete Provider Lifecycle and Workflow Execution
Purpose:
Validate the integrated provider lifecycle, workflow execution, recovery logic, checkpoint resume, and idempotency guarantees across the core runtime components.

Pass criteria:
- AtrinDatabase initializes successfully with WAL mode
- Provider registration and provider profile creation succeed
- Auth states transition through UNKNOWN -> NOT_AUTHENTICATED -> LOGIN_REQUIRED -> AUTHENTICATING -> AUTHENTICATED -> ACTIVE without error
- Workflow creation and multi-step task execution succeed
- A simulated network interruption triggers the recovery path
- RecoveryEngine sets the workflow to a recoverable waiting state and resumes from checkpoint
- Replay of the same action is treated as idempotent and is not re-executed
- Audit log records all state transitions
- Cleanup removes temporary records without affecting the rest of the system

### 2. UI smoke coverage
Purpose:
Validate the desktop application navigation and core page scaffolding remain available to end users.

Pass criteria:
- Dashboard route is available
- Providers route is available
- Workflows route is available
- Recovery route is available
- Settings route is available
- First-run wizard route is available
- Provider page renders mock provider data
- Workflow page renders mock workflow data

## Known limitations
- The UI smoke validation is implemented as an automated source-level validation for the route declarations and mock data binding, not a full browser-driven interaction test.
- The repository currently validates the desktop app structure and core runtime behaviors without requiring a live external browser session.
- External service and real API calls remain stubbed to preserve deterministic execution in CI and local runs.

## Local execution instructions
From the repository root:

```bash
pytest tests/test_e2e_acceptance.py -v
pytest tests/test_e2e_ui_smoke.py -v
```

Or run both as a combined check:

```bash
pytest tests/test_e2e_acceptance.py tests/test_e2e_ui_smoke.py -v
```

## Manual follow-up
For a human validation pass, use the desktop app to confirm:
- provider registration persists correctly across sessions
- workflow execution resumes after a simulated outage
- recovery prompts and state indicators are visible to the user
- the first-run wizard is accessible from the application shell
