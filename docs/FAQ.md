# Atrin AI Control Plane v2.3 FAQ

## Table of Contents

- [General Questions](#general-questions)
- [User Questions](#user-questions)
- [Developer Questions](#developer-questions)
- [Security and Privacy](#security-and-privacy)

## General Questions

### What is Atrin?

Atrin is a local-first control plane for configuring, authenticating, orchestrating, supervising, and recovering workflows across heterogeneous AI providers and execution tools.

### Is Atrin tied to one AI vendor?

No. Providers are adapters selected by capability. The core workflow engine does not depend on a vendor, model family, browser site, or desktop application.

### Is Atrin a hosted service?

The v2.3 implementation is designed for local-first desktop operation. The runtime binds to `127.0.0.1` by default, and the Tauri configuration prepares a Windows desktop package.

### What is complete in v2.3?

The repository reports all 13 implementation phases complete, including core contracts, persistence, session management, workflows, execution, recovery, security guardrails, adapters, UI shell, packaging foundation, and automated verification. External service calls remain stubbed in tests, and the frontend is currently mock-backed.

## User Questions

### How do I start Atrin?

Install the Python and frontend dependencies, start `uvicorn atrin_core.runtime:app --host 127.0.0.1 --port 8765`, and run `npm run dev` from `frontend`. See [USER_GUIDE.md](USER_GUIDE.md).

### Where is my data stored?

SQLite data is stored wherever you pass as `db_path`; `.atrin_data/atrin.db` is the recommended local path. Browser profiles use `ATRIN_BROWSER_PROFILES_DIR` or the platform default. The runtime token is `.atrin_data/runtime_secret.token`.

### What happens when a provider goes offline?

Atrin preserves the latest checkpoint and moves the workflow into a reason-specific waiting state, such as `WAITING_FOR_NETWORK` or `WAITING_FOR_PROVIDER`. After the provider returns, resume from Recovery.

### Why does the UI show sample providers or workflows?

The v2.3 React screens intentionally use deterministic mock data. They demonstrate navigation and presentation while the backend integration surface is completed.

### Can I run the Windows installer on Linux?

No. The Tauri installer must be built on a Windows machine with the Windows target toolchain and WebView2 requirements. Linux and WSL2 are suitable for core development and testing.

## Developer Questions

### Which API endpoints exist?

Only `GET /health` and authenticated `GET /api/v1/status` are currently implemented. Workflow, session, provider, and recovery operations are Python service APIs, not HTTP endpoints. See [API_REFERENCE.md](API_REFERENCE.md).

### How do I add a provider?

Implement or configure an adapter that satisfies the generic provider contract, register it with the runtime or workflow engine, and expose only capability-neutral behavior to orchestration code. Do not add vendor conditionals to the core.

### Why are checkpoints and idempotency separate?

A checkpoint describes where a workflow can safely resume. The idempotency ledger identifies a side effect so a retry can determine whether the same action was already confirmed. Both are needed for durable execution.

### How is the project tested?

Run `pytest` for the Python suite. Acceptance and UI smoke checks can be run with `pytest tests/test_e2e_acceptance.py tests/test_e2e_ui_smoke.py -v`. The UI smoke test is source-level validation rather than browser-driven interaction.

### What frontend stack is used?

The frontend uses React 19, TypeScript, Vite, React Router, and Zustand. Tauri 2 provides the Windows desktop shell.

## Security and Privacy

### Is the runtime token a provider credential?

No. It authenticates local requests to the runtime. Provider credentials and browser sessions are separate and must be protected using the provider's supported secure mechanism.

### How is the runtime token protected?

It is generated with a secure random source, stored in the configured token file, compared using a constant-time comparison, and assigned mode `0600` when created on platforms that support it.

### Does Atrin send workflow data to a central service?

The v2.3 core is local-first. Provider adapters may communicate with their configured external service, but the repository does not define a central telemetry service. Review each adapter and deployment network policy before handling sensitive data.

### Should logs include tokens or cookies?

Never. Redact runtime tokens, authorization headers, cookies, browser profile contents, personal information, and provider payloads before sharing diagnostics.

### Does Atrin guarantee that a retry is harmless?

No system can infer safety for every external side effect. Atrin records idempotency keys and checkpoints, but operators must verify remote state and evidence before retrying actions that may already have succeeded.
