# Atrin AI Control Plane

[![CI](https://img.shields.io/badge/tests-passing-brightgreen)](tests/)
[![Version](https://img.shields.io/badge/version-2.3-blue)](docs/CHANGELOG.md)
[![License](https://img.shields.io/badge/license-see%20repository-lightgrey)](README.md#license)

Atrin is a local-first, vendor-neutral AI control plane for configuring providers, managing authenticated sessions, orchestrating multi-step workflows, and recovering safely from interruptions. Provider-specific behavior is isolated behind adapters, allowing the orchestration core to remain independent of any AI vendor, model, browser application, or execution tool.

## Table of Contents

- [Documentation](#documentation)
- [Quick Start](#quick-start)
- [Provider Configuration](#provider-configuration)
- [Architecture](#architecture)
- [Development](#development)
- [Contributing](#contributing)
- [License](#license)

## Documentation

- [User Guide](docs/USER_GUIDE.md): concepts, quick start, daily operations, and user troubleshooting.
- [Installation](docs/INSTALLATION.md): Windows, WSL2, Linux, Docker guidance, development, and deployment.
- [Troubleshooting](docs/TROUBLESHOOTING.md): diagnostics, error messages, and recovery steps.
- [API Reference](docs/API_REFERENCE.md): implemented HTTP endpoints and Python core services.
- [FAQ](docs/FAQ.md): user, developer, security, and privacy questions.
- [Changelog](docs/CHANGELOG.md): v2.3 features, phases, breaking changes, and known issues.
- [Build Instructions](BUILD_INSTRUCTIONS.md): Windows Tauri packaging.
- [Project Status](docs/PROJECT_STATUS.md): current implementation and release position.

## Quick Start

Requirements: Python 3.10+, Node.js 18+, npm, Git, and 2 GB free storage.

```bash
git clone https://github.com/mahmadifarpooyagroup-png/Execute-and-provide-output.git
cd Execute-and-provide-output
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e '.[dev]'
python -c "from atrin_core.database import AtrinDatabase; AtrinDatabase('.atrin_data/atrin.db')"
```

In one terminal, start the local runtime:

```bash
uvicorn atrin_core.runtime:create_app --factory --host 127.0.0.1 --port 8765
```

In a second terminal, start the frontend:

```bash
cd frontend
npm install
npm run dev
```

Open the Vite URL printed in the terminal, normally `http://localhost:5173`. The runtime health endpoint is public; control-plane API endpoints require the local runtime token stored by the backend.

## Provider Configuration

The provider registry is configuration-driven and remains vendor-neutral. Set `ATRIN_PROVIDERS_JSON` to a JSON array or point `ATRIN_PROVIDERS_FILE` at a JSON file. Credentials belong in environment variables, never in source control.

Example API provider:

```json
[
  {
    "id": "my-api",
    "name": "My API",
    "adapter_id": "openai-compatible",
    "connection_kind": "API",
    "endpoint": "https://example.invalid/v1",
    "metadata": {
      "api": {
        "model": "my-model",
        "api_key_env": "MY_API_KEY"
      },
      "capabilities": ["chat"]
    }
  }
]
```

The built-in adapter IDs are `web`, `generic-web`, `api`, `openai-compatible`, `mcp`, `a2a`, and `acp`. Web providers use selector configuration such as `start_url`, `composer_selector`, `send_selector`, `response_selector`, and optional `profile_path` under `metadata.web`.

The desktop UI exposes the configured provider catalog through **Providers** and persists provider profiles in SQLite. Workflows can then be created and controlled from **Workflows**, including run-next, pause, resume, cancel, and live refresh of state.

## Architecture

```text
User
	|
Tauri 2 desktop shell / React + TypeScript UI
	|
Authenticated Local FastAPI runtime (127.0.0.1:8765)
	|
Provider Registry -- Workflow Engine -- Execution Bus
	|                    |                |
Provider Profiles      SQLite          Permission / timeout controls
	|                    |
Adapters               Checkpoints / idempotency / audit
	|
Web | Desktop | API | MCP | A2A | ACP
```

Workflows remain authoritative inside Atrin even when an external provider session pauses, expires, or reconnects. SQLite uses WAL mode and stores provider profiles, sessions, workflows, tasks, steps, checkpoints, idempotency records, plugin registry metadata, and audit events.

## Development

```bash
pytest
cd frontend && npm run lint && npm run build
```

Run deterministic acceptance checks with:

```bash
pytest tests/test_e2e_acceptance.py tests/test_e2e_ui_smoke.py -v
```

The CI pipeline also runs a real Playwright browser journey against a deterministic test provider, covering provider profile creation, workflow creation, execution, completion, and dashboard refresh.

For a Windows installer, install Rust stable, WebView2, and the native build tools, then run `npm run tauri build` from `frontend` on Windows.

## Contributing

1. Create a focused branch from `main`.
2. Keep provider-specific behavior behind adapter contracts; do not add vendor conditionals to the core.
3. Add or update focused tests for behavior changes.
4. Run the Python tests and frontend lint/build checks.
5. Update the relevant documentation and open a pull request with the rationale, validation, and known limitations.

## License

No license file is currently present in the repository. Treat the project as unlicensed until the maintainers add and publish a license. Do not redistribute it as open-source software without explicit permission.
