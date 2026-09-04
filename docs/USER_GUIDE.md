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
- Durable SQLite storage with WAL mode for workflows, sessions, checkpoints, and audit records.
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

Initialize a database by constructing `AtrinDatabase` with a path, for example:

```bash
python -c "from atrin_core.database import AtrinDatabase; AtrinDatabase('.atrin_data/atrin.db')"
```

The runtime creates `.atrin_data/runtime_secret.token` on first authenticated status check. Protect this file and do not commit it. Complete provider and account setup through the first-run flow or the corresponding core service APIs.

## Quick Start Tutorial

### 1. Start the application

Start the local backend from the repository root:

```bash
uvicorn atrin_core.runtime:app --host 127.0.0.1 --port 8765
```

In a second terminal, start the frontend:

```bash
cd frontend
npm run dev
```

Open the Vite URL shown in the terminal, normally `http://localhost:5173`. The Tauri desktop shell can be built with `npm run tauri build` from `frontend` on a Windows build machine.

### 2. Create your first workflow

Open **Workflows**, define a goal, split it into ordered tasks, and assign each task's steps to a provider capable of performing the action. Save the workflow before execution so its initial checkpoint exists.

### 3. Connect an AI provider

Open **Providers**, register a provider adapter and a provider profile for the account or environment that will execute the workflow. Authenticate once and confirm that the profile reaches an active state. Keep provider credentials in the provider's secure configuration; never place secrets in source control.

### 4. Execute a simple task

Select a workflow with one safe, reversible step, then start the step. Atrin records the pre-action state, executes through the selected adapter, records the result and evidence, and advances the workflow only after confirmation.

### 5. Monitor progress

Use **Dashboard** and **Workflows** to inspect state and progress. Use **Recovery** when a workflow is waiting for authentication, network availability, a provider, or human approval. Resume only after the underlying condition is resolved.

> **v2.3 status:** The current frontend is a navigation and UI foundation backed by deterministic mock data. The Python core and tests exercise real workflow, session, provider, and recovery behavior; the frontend does not yet call the backend REST API.

## Core Concepts

### Workflows and Tasks

A workflow has a goal and durable state. It contains ordered tasks, and each task contains ordered steps. A step names an action, provider, idempotency key, result, and evidence. Workflow state is independent of any provider session.

Typical states include `IDLE`, `OBSERVING`, `EXECUTING`, `FAILED`, and recoverable `WAITING_FOR_*` states.

### Providers and Adapters

A provider describes capabilities and health. An adapter translates Atrin's generic contract to a web page, desktop application, API, CLI, MCP server, A2A agent, or ACP agent. Provider-specific selectors, endpoints, and protocol details belong in the adapter, not the workflow engine.

### Sessions and Authentication

A provider profile represents an account or execution context. Sessions have their own lifecycle, lock owner, lease, and fencing token. Authentication transitions are explicit, allowing Atrin to distinguish an unknown account, a login requirement, an active session, and an expired session.

### Checkpoints and Recovery

Atrin persists a checkpoint before risky work and after state changes. A network outage is not treated as an authentication failure. Recovery pauses the workflow in a reason-specific waiting state, preserves the latest safe checkpoint, and resumes from that checkpoint after the dependency is available.

### Execution Bus and Permissions

The execution bus is the boundary for dispatching work to adapters. Permission checks and capability matching happen before an action is sent to a provider. The idempotency ledger records a step's identity so retries do not blindly repeat a confirmed side effect. Audit records provide an operational history.

## Daily Operations

### Creating workflows

Start with a measurable goal. Use small, ordered tasks; select providers by capability; make actions idempotent where possible; and verify the expected result or evidence for every external side effect.

### Managing providers

Review provider health and authentication state before starting work. Keep separate profiles for separate accounts or environments. Replace a provider only with another provider that satisfies the required capability profile.

### Handling authentication challenges

When a workflow enters `WAITING_FOR_AUTH`, authenticate in the provider's normal interface, verify the session is active, and resume from Recovery. Do not delete the workflow or rerun all previous steps.

### Using the Recovery Center

Prioritize high-impact waits first. Inspect the pause reason and checkpoint, correct the provider, network, or approval condition, then resume. If the checkpoint is no longer safe, mark the workflow failed and create a new controlled run.

### Viewing logs and evidence

Use application logs for runtime diagnostics and the audit log for workflow history. Step evidence should identify what was observed or confirmed. Do not put access tokens, cookies, or other secrets in evidence or support bundles.

## Troubleshooting

- **The runtime will not start:** Confirm Python dependencies are installed and port 8765 is free. Run `python -m pip install -e '.[dev]'` again inside the active virtual environment.
- **The UI is blank:** Confirm `npm install` and `npm run dev` completed, then inspect browser developer-console errors. Use the exact Vite URL printed by the command.
- **Network errors:** Check DNS, proxy, firewall, provider availability, and the local clock. A timeout should be handled as a network wait, not as an authentication failure.
- **Authentication failures:** Re-authenticate the provider profile, confirm its session is active, and resume from the checkpoint. Rotate the local runtime token only as an administrative action.
- **Workflow stuck in `WAITING_FOR_*`:** Read the reason in the checkpoint and Recovery view. Resolve the named dependency, then resume; do not replay completed steps manually.
- **Performance issues:** Check available RAM and disk, close unnecessary browser sessions, inspect database size and logs, and avoid parallel workflows that contend for one provider profile.

For detailed diagnostics, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## Current v2.3 Scope

All 13 implementation phases are represented in the repository, including core contracts, persistence, sessions, workflow execution, recovery, security guardrails, adapters, desktop shell, packaging foundation, and verification. The Windows installer configuration is present but must be built on a Windows machine. External service calls are stubbed in automated tests, and the frontend data layer remains mock-backed.

See [CHANGELOG.md](CHANGELOG.md) for the release record and [API_REFERENCE.md](API_REFERENCE.md) for the currently implemented HTTP contract.
