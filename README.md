# Atrin AI Control Plane

[![CI](https://img.shields.io/badge/tests-passing-brightgreen)](tests/)
[![Version](https://img.shields.io/badge/version-2.3-blue)](docs/CHANGELOG.md)
[![License](https://img.shields.io/badge/license-see%20repository-lightgrey)](README.md#license)

Atrin is a local-first, vendor-neutral AI control plane for configuring providers, managing authenticated sessions, orchestrating multi-step workflows, and recovering safely from interruptions. Provider-specific behavior is isolated behind adapters, allowing the orchestration core to remain independent of any AI vendor, model, browser application, or execution tool.

## Table of Contents

- [Documentation](#documentation)
- [Quick Start](#quick-start)
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
uvicorn atrin_core.runtime:app --host 127.0.0.1 --port 8765
```

In a second terminal, start the frontend:

```bash
cd frontend
npm install
npm run dev
```

Open the Vite URL printed in the terminal, normally `http://localhost:5173`. Check the runtime with `curl http://127.0.0.1:8765/health`.

> **Current scope:** The v2.3 React screens are a desktop UI foundation backed by deterministic mock data. The Python core, SQLite persistence, workflow engine, recovery engine, adapters, and automated tests are implemented. The HTTP API currently exposes health and authenticated runtime status only.

## Architecture

```text
User
	|
Tauri 2 desktop shell / React + TypeScript UI
	|
Local FastAPI runtime (127.0.0.1:8765)
	|
Vendor-neutral workflow engine -- execution bus -- permission checks
	|                         |
SQLite + checkpoints       Provider adapters
	|                         |
Audit + idempotency         Web | Desktop | API | MCP | A2A | ACP
```

Workflows remain authoritative inside Atrin even when an external provider session pauses, expires, or reconnects. SQLite uses WAL mode and stores provider profiles, sessions, workflows, tasks, steps, checkpoints, idempotency records, and audit events.

## Development

```bash
pytest
cd frontend && npm run lint && npm run build
```

Run the acceptance and UI smoke checks with:

```bash
pytest tests/test_e2e_acceptance.py tests/test_e2e_ui_smoke.py -v
```

For a Windows installer, install Rust stable, WebView2, and the native build tools, then run `npm run tauri build` from `frontend` on Windows.

## Contributing

1. Create a focused branch from `main`.
2. Keep provider-specific behavior behind adapter contracts; do not add vendor conditionals to the core.
3. Add or update focused tests for behavior changes.
4. Run the Python tests and frontend lint/build checks.
5. Update the relevant documentation and open a pull request with the rationale, validation, and known limitations.

## License

No license file is currently present in the repository. Treat the project as unlicensed until the maintainers add and publish a license. Do not redistribute it as open-source software without explicit permission.