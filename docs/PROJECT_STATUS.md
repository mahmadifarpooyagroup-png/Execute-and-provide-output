# Atrin AI Control Plane — Project Status

Date: 2026-09-07

## Current status

`main` is the single active development line. The durable workflow core, SQLite persistence, session leasing/fencing, checkpoint recovery, authenticated local API, configuration-driven provider registry, frontend runtime integration, plugin persistence/isolation, Tauri packaging, and CI verification are implemented.

## Verified in CI

The release gate runs:

- Python 3.10, 3.11, 3.12, 3.13, and 3.14
- Python compilation, Ruff, mypy, Bandit, and the full Python test suite
- Frontend dependency installation, lint, and production build
- Real Playwright browser E2E using a deterministic provider
- Tauri Rust formatting and Linux compilation with `cargo check --locked`
- Windows Tauri NSIS packaging and installer artifact upload

## Operational product path

The normal flow is:

`Tauri/React UI -> authenticated local FastAPI -> ProviderAdapterRegistry -> WorkflowEngine -> adapter -> provider`

Provider profiles and workflow steps are durable in SQLite. The UI now consumes the runtime API for provider catalog, provider profiles, workflow list/detail, workflow controls, recovery, and audit data rather than deterministic mock services.

## Provider architecture

Provider configuration is vendor-neutral. Built-in adapter IDs include:

- `web` / `generic-web`
- `api` / `chat-completions`
- `mcp`
- `a2a`
- `acp`

Credentials are referenced through environment variables and are not stored in provider configuration examples.

## Security position

- Runtime binds to loopback by default.
- Protected API routes require the local runtime token.
- SQLite enables foreign keys, WAL, and a busy timeout per connection.
- Session lease ownership and fencing tokens are durable.
- Ambiguous external side effects are not silently retried.
- Plugins execute in dedicated worker processes and use persisted file hashes for restore validation.
- Plugin worker isolation is not equivalent to a full OS/container sandbox; untrusted plugin uploads remain unsupported.
- Browser profiles must be isolated per provider/account and treated as sensitive credential stores.

## Remaining release validation

These are environment-specific rather than known broken-code defects:

1. Validate real provider adapters against each provider/account configuration with real credentials in a controlled environment.
2. Validate the signed Windows installer and first launch on a clean target machine.
3. Add an OS-native secure secret provider when higher-assurance credential storage is required outside the current runtime-token controls.
4. Introduce stronger OS/container isolation before accepting untrusted third-party plugins.

## Release position

The repository is a **hardened RC baseline**. Core CI, frontend build, browser E2E, Tauri Linux checks, and Windows NSIS packaging must remain green. Production rollout requires provider-specific environment validation and trusted-plugin/credential policies; CI success is not a guarantee that every arbitrary external provider or deployment environment is compatible.
