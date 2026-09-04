# Atrin AI Control Plane v2.3 Installation

## Table of Contents

- [Before You Begin](#before-you-begin)
- [Windows Native](#windows-native)
- [Windows WSL2](#windows-wsl2)
- [Linux Ubuntu/Debian](#linux-ubuntudebian)
- [Linux Arch/RHEL](#linux-archrhel)
- [Docker Installation](#docker-installation)
- [Development Environment](#development-environment)
- [Production Deployment](#production-deployment)
- [Configuration Options](#configuration-options)
- [Verification](#verification)

## Before You Begin

Atrin requires Python 3.10+, Node.js 18+, npm, Git, and 2 GB free disk space. Use Python 3.12+ and Node.js 20+ for Windows packaging. Rust stable, Microsoft Visual C++ Build Tools, and WebView2 are required for a Tauri installer.

## Windows Native

1. Install Git, Python 3.10+, and Node.js 18+ from their official installers. Select the option that adds Python and Node.js to `PATH`.
2. Open PowerShell and clone the repository:

```powershell
git clone https://github.com/mahmadifarpooyagroup-png/Execute-and-provide-output.git
cd Execute-and-provide-output
```

3. Create and activate a virtual environment:

```powershell
py -3 -m venv .venv
.venv\\Scripts\\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

4. Install and build the frontend:

```powershell
cd frontend
npm install
npm run build
cd ..
```

5. Initialize SQLite and start the runtime:

```powershell
python -c "from atrin_core.database import AtrinDatabase; AtrinDatabase('.atrin_data\\atrin.db')"
uvicorn atrin_core.runtime:app --host 127.0.0.1 --port 8765
```

PowerShell may require `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` before activating a virtual environment. For a desktop installer, install Rust stable and WebView2, then run `npm run tauri build` from `frontend`.

## Windows WSL2

Install WSL2 with an Ubuntu distribution, then follow the Ubuntu/Debian steps inside the WSL terminal. Keep the repository in the Linux filesystem, such as `~/src`, for better file-system performance. Use the Windows-native Tauri toolchain separately when producing an installer.

The frontend can be opened from Windows using the Vite URL. Bind the backend to `127.0.0.1` unless a deliberate, protected network topology requires otherwise.

## Linux Ubuntu/Debian

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip nodejs npm

git clone https://github.com/mahmadifarpooyagroup-png/Execute-and-provide-output.git
cd Execute-and-provide-output
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e '.[dev]'
cd frontend
npm install
npm run build
cd ..
python -c "from atrin_core.database import AtrinDatabase; AtrinDatabase('.atrin_data/atrin.db')"
```

Use a current Node.js LTS release if the distribution package is older than Node.js 18.

## Linux Arch/RHEL

Arch Linux:

```bash
sudo pacman -S --needed git python python-pip nodejs npm
```

RHEL/Fedora-compatible systems:

```bash
sudo dnf install -y git python3 python3-pip nodejs npm
```

Then run the common setup from the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e '.[dev]'
cd frontend && npm install && npm run build
```

## Docker Installation

Docker support is optional. This repository does not currently ship a Dockerfile or compose file. A deployment image must provide Python 3.10+, the installed `atrin-core` package, and a persistent volume for `.atrin_data` and any browser profiles. Do not expose the development server directly to the public internet; put it behind an authenticated reverse proxy and TLS.

A minimal image build outline is:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -e .
EXPOSE 8765
CMD ["uvicorn", "atrin_core.runtime:app", "--host", "127.0.0.1", "--port", "8765"]
```

This is a starting point, not a production image. Add a non-root user, health checks, dependency pinning, and a secure network policy before deployment.

## Development Environment

Install development dependencies with `pip install -e '.[dev]'`. Run the backend with Uvicorn and the frontend with Vite:

```bash
uvicorn atrin_core.runtime:app --host 127.0.0.1 --port 8765
cd frontend && npm run dev
```

Useful checks:

```bash
pytest
cd frontend && npm run lint && npm run build
```

## Production Deployment

The current runtime is local-first and intentionally binds to loopback. For a controlled deployment:

1. Use a dedicated OS account and a locked-down virtual environment or container.
2. Store `.atrin_data` on persistent storage with restricted permissions and backups.
3. Protect `.atrin_data/runtime_secret.token`; treat it as a local runtime credential.
4. Keep the service on loopback or place it behind a TLS reverse proxy with network access controls.
5. Configure process supervision, log rotation, resource limits, and a restart policy.
6. Run database backups and test checkpoint restoration before enabling unattended workflows.
7. Build the Windows Tauri installer on a Windows host with the required Rust and WebView2 tooling.

The repository does not yet provide a production service unit, Docker image, reverse-proxy configuration, or full HTTP CRUD API. These must be supplied by the deployment owner.

## Configuration Options

### Runtime arguments

`start_runtime(host="127.0.0.1", port=8765)` controls the bind address and port. The direct Uvicorn equivalent is:

```bash
uvicorn atrin_core.runtime:app --host 127.0.0.1 --port 8765
```

Do not bind to `0.0.0.0` without a reviewed security boundary.

### Environment variables

- `ATRIN_BROWSER_PROFILES_DIR`: optional directory for browser profiles on non-Windows systems. The default is `~/.local/share/Atrin/BrowserProfiles`.

The current runtime does not define a general environment-variable configuration loader. Database paths are passed to `AtrinDatabase(db_path)`, and the runtime token path defaults to `.atrin_data/runtime_secret.token` in `LocalSecurityManager`.

### Files and paths

- `.atrin_data/atrin.db`: recommended SQLite database path; created when `AtrinDatabase` is initialized.
- `.atrin_data/runtime_secret.token`: generated local API token; keep private.
- Browser profiles: `ATRIN_BROWSER_PROFILES_DIR` or the platform default described above.

## Verification

```bash
curl http://127.0.0.1:8765/health
pytest tests/test_e2e_acceptance.py tests/test_e2e_ui_smoke.py -v
```

Expected health response:

```json
{"status":"healthy","service":"atrin-control-plane"}
```
