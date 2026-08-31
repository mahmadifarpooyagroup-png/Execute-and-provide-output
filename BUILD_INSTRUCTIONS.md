# Atrin Windows Installer Build Instructions

This document describes how to build the Windows installer for the Atrin AI Control Plane using Tauri 2.

## Prerequisites

Install the following on a local Windows machine:

- Node.js 20+ and npm
- Rust stable toolchain (`rustup-init` / `rustc` / `cargo`)
- Python 3.12+
- WebView2 Runtime (the installer can bundle an offline installer automatically)
- Git

## Recommended environment

- Windows 10 or 11
- Microsoft Visual C++ Build Tools (for native dependencies)
- Administrator access for installation testing

## One-time setup

```powershell
cd path\to\Execute-and-provide-output\frontend
npm install
npm install @tauri-apps/cli @tauri-apps/api
cargo --version
python --version
```

## Build the React app

```powershell
cd path\to\Execute-and-provide-output\frontend
npm run build
```

## Build the Windows installer

```powershell
cd path\to\Execute-and-provide-output\frontend
npm run tauri build
```

This produces a Windows installer artifact in the `src-tauri/target/release/bundle/nsis/` directory. The output is typically named similarly to:

- `Atrin AI Control Plane_0.1.0_x64-setup.exe`
- or `Atrin-Setup.exe` depending on the final packaging configuration and naming conventions

## WebView2 requirement

Tauri config is set to use WebView2 with an offline installer fallback:

```json
"webviewInstallMode": {
  "type": "offlineInstaller",
  "silent": true
}
```

This allows the installer to include the WebView2 bootstrapper offline and avoids requiring an active network connection at install time.

## Python runtime and Atrin project dependency setup

The repository includes a PowerShell helper at:

- `frontend/scripts/ensure-python-runtime.ps1`

This script checks that Python is installed, ensures `pip` is updated, and installs the local Atrin project in editable mode so the runtime package is accessible.

Run it before launching the application in a packaged environment:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\ensure-python-runtime.ps1
```

## Product and installer details

The Tauri configuration currently sets:

- App identifier: `com.atrin.controlplane`
- Window title: `Atrin AI Control Plane`
- Windows installer target: NSIS
- Start Menu entry: enabled via `startMenuFolder`
- Desktop shortcut: optional and can be enabled by the Windows installer flow or by additional customization if needed

## Notes

- The current Codespace environment does not include a Windows target toolchain, so a full `tauri build` cannot be completed here.
- The Tauri configuration and packaging setup are prepared for local Windows building and installer generation in accordance with the spec.
