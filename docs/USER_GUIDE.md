# Atrin AI Control Plane v2.3 User Guide

## Table of Contents

- [Introduction](#introduction)
- [System Requirements](#system-requirements)
- [Installation Guide](#installation-guide)
- [Quick Start Tutorial](#quick-start-tutorial)
- [Core Concepts](#core-concepts)
- [Daily Operations](#daily-operations)
- [Troubleshooting](#troubleshooting)
- [Current v2.3 Scope](#current-v23-scope)

## Introduction

Atrin is a local-first, vendor-neutral AI control plane. It gives people one place to configure providers, authenticate accounts, orchestrate multi-step workflows, supervise execution, and recover from interruptions. Provider-specific behavior is isolated behind adapters, so changing a provider does not require changing the orchestration core.

Key features include:

- Provider-neutral adapters for web, desktop, API, MCP, A2A, and ACP integrations.
- A configuration-driven provider adapter registry with a runtime provider catalog.
- Durable SQLite storage with WAL mode for workflows, sessions, checkpoints, provider profiles, and audit records.
- Explicit authentication and session lifecycle management.
- Checkpoint-based recovery for network, authentication, provider, and human-interaction pauses.
- Idempotency tracking to reduce duplicate side effects when a step is retried.
- A Tauri desktop shell with Dashboard, Providers, Workflows, Recovery, Settings, and first-run screens.

## System Requirements

- Windows 10 or Windows 11, with WSL2 when Linux tooling is needed, or Linux.
- RAM: 4 GB minimum; 8 GB recommended.
- Storage: 2 GB free space, plus space for browser profiles and logs.
- Python 3.10 or newer.
- Node.js 18 or newer and npm for the frontend.
- Git.
- Rust stable and Microsoft WebView2 are additionally required to build the Windows Tauri installer.

## Installation Guide

For platform-specific instructions, see [INSTALLATION.md](INSTALLATION.md). The short path is:

```bash
git clone https://github.com/mahmadifarpooyagroup-png/Execute-and-provide-output.git
cd Execute-and-provide-output
python -m venv .venv
# Linux/macOS/WSL2
source .venv/bin/activate
# Windows PowerShell: .venv\\Scripts\\Activate.ps1
python -m pip install --upgrade pip
pip install -e '.[dev]'
cd frontend
npm install
cd ..
```

Initialize the database:

```bash
python -c "from atrin_core.database import AtrinDatabase; AtrinDatabase('.atrin_data/atrin.db')"
```

The runtime creates `.atrin_data/runtime_secret.token` on first use. Protect this file and do not commit it.

## Quick Start Tutorial

### 1. Configure an adapter

Set `ATRIN_PROVIDERS_JSON` or `ATRIN_PROVIDERS_FILE` before starting the runtime. For API providers, reference a credential environment variable through `metadata.api.api_key_env`; do not put credentials in the JSON file.

Example:

```bash
export ATRIN_PROVIDERS_JSON='[{"id":"my-api","name":"My API","adapter_id":"openai-compatible","connection_kind":"API","endpoint":"https://example.invalid/v1","metadata":{"api":{"model":"my-model","api_key_env":"MY_API_KEY"},"capabilities":["chat"]}}]'
export MY_API_KEY='replace-me'
```

For browser providers, configure `metadata.web` selectors and optionally a persistent `profile_path` so the browser session can be reused after a manual login.

### 2. Start the application

Start the local backend from the repository root:

```bash
uvicorn atrin_core.runtime:app --host 127.0.0.1 --port 8765
```

In a second terminal, start the frontend:

```bash
cd frontend
npm run dev
```

Open the Vite URL shown in the terminal, normally `http://localhost:5173`.

### 3. Add a provider profile

Open **Providers**. Atrin loads the provider catalog from the runtime, then lets you create a durable profile containing a profile ID, account ID, and display name. Keep separate profiles for separate accounts or environments.

### 4. Create and execute a workflow

Open **Workflows**, choose a configured provider profile, enter a goal and first action, and create the workflow. Use **Run next** to execute the next pending step. The page refreshes active workflow state automatically.

Use **Pause**, **Resume**, and **Cancel** for lifecycle control. Cancellation remains conservative: if an external provider does not confirm cancellation, Atrin keeps the workflow in a recovery state rather than falsely marking it cancelled.

### 5. Handle recovery

Use **Recovery** when a workflow is waiting for authentication, network availability, a provider, or human approval. Resolve the underlying condition, then resume from the saved checkpoint.

## Core Concepts

### Workflows and Tasks

A workflow has a goal and durable state. It contains ordered tasks, and each task contains ordered steps. A step names an action, provider, idempotency key, operation ID, result, and evidence. Workflow state is independent of any provider session.

Typical states include `IDLE`, `OBSERVING`, `EXECUTING`, `FAILED`, and recoverable `WAITING_FOR_*` states.

### Providers and Adapters

A provider describes capabilities and health. The provider registry maps an `adapter_id` to an executable adapter. An adapter translates Atrin's generic contract to a web page, desktop application, API, CLI, MCP server, A2A agent, or ACP agent. Provider-specific selectors, endpoints, and protocol details belong in configuration/adapter code, not the workflow engine.

### Sessions and Authentication

A provider profile represents an account or execution context. Sessions have their own lifecycle, lock owner, lease, and fencing token. Authentication transitions are explicit, allowing Atrin to distinguish an unknown account, a login requirement, an active session, and an expired session.

### Checkpoints and Recovery

Atrin persists checkpoints before risky work and after state changes. A network outage is not treated as an authentication failure. Recovery pauses the workflow in a reason-specific waiting state, preserves the latest safe checkpoint, and resumes from that checkpoint after the dependency is available.

### Execution Bus and Permissions

The execution bus is the boundary for dispatching work. Permission checks and capability matching happen before an action is sent to a provider. The idempotency ledger records a step's identity so retries do not blindly repeat a confirmed side effect. Audit records provide an operational history.

## Daily Operations

### Managing providers

Review the provider catalog before creating profiles. For browser adapters, use a dedicated persistent browser profile per account and never share profile directories between unrelated providers or accounts.

### Handling authentication challenges

When a workflow enters `WAITING_FOR_AUTH`, authenticate in the provider's normal interface, verify the session is active, and resume from Recovery. Do not delete the workflow or rerun completed steps.

### Using the Recovery Center

Prioritize high-impact waits first. Inspect the pause reason and checkpoint, correct the provider, network, or approval condition, then resume. If the checkpoint is no longer safe, mark the workflow failed and create a new controlled run.

### Viewing logs and evidence

Use application logs for runtime diagnostics and the audit log for workflow history. Step evidence should identify what was observed or confirmed. Do not put access tokens, cookies, or other secrets in evidence or support bundles.

## Troubleshooting

- **The provider catalog is empty:** Confirm `ATRIN_PROVIDERS_JSON` or `ATRIN_PROVIDERS_FILE` is set in the same environment used to start the runtime.
- **The runtime will not start:** Confirm Python dependencies are installed and port 8765 is free.
- **The UI is blank:** Confirm `npm install` and `npm run dev` completed, then inspect browser developer-console errors.
- **API authentication fails:** Enter the runtime token in Settings. The desktop UI keeps it only in the current session.
- **A workflow cannot execute:** Confirm its provider ID is configured, the profile belongs to that provider, the provider credential/session is available, and the step has the required capability.
- **Authentication or network wait:** Resolve the underlying condition and resume from Recovery; do not replay completed steps manually.
- **Performance issues:** Check available RAM and disk, close unnecessary browser sessions, inspect database size and logs, and avoid parallel workflows that contend for one provider profile.

For detailed diagnostics, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## Current v2.3 Scope

The core workflow, persistence, session, recovery, security, provider registry, frontend runtime integration, Tauri packaging, and automated verification paths are implemented. The CI pipeline includes real Playwright coverage using a deterministic provider to validate provider onboarding and the workflow execution journey without exposing real credentials.

Production rollout still requires provider-specific configuration and validation with real credentials, clean-machine Windows installation validation, and stronger OS/container isolation for untrusted plugins. See [PROJECT_STATUS.md](PROJECT_STATUS.md) for the current release position.
