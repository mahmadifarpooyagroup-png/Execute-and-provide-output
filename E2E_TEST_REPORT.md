# E2E Test Report

Date: 2026-09-07

## Scope

The automated acceptance surface now includes a real browser-driven journey against a deterministic local provider. The test starts the real FastAPI runtime, builds the real React application, serves the production frontend bundle, launches Chromium through Playwright, and exercises the UI through the authenticated runtime API.

## Browser journey

1. Open the frontend.
2. Seed the local runtime token in session-scoped browser storage.
3. Open Providers.
4. Read the provider catalog from the runtime.
5. Create a durable provider profile.
6. Open Workflows.
7. Create a workflow from the selected provider profile.
8. Run the pending step through the workflow engine and deterministic provider adapter.
9. Confirm the workflow reaches 100% and `completed`.
10. Return to Dashboard and verify refreshed runtime data is visible.

## Additional automated coverage

The Python matrix checks 3.10 through 3.14 and runs syntax compilation, Ruff, mypy, Bandit, and the full test suite. Frontend CI runs lint and production build. Tauri CI runs Rust formatting and locked Linux compilation. Windows CI builds the NSIS installer and uploads the artifact.

## Interpretation

The browser test proves UI-to-API-to-runtime integration for the deterministic test provider. It does not claim successful interoperability with every real external provider. Real credentials and provider sessions remain environment-specific validation.

## Known limitations

- Real third-party provider credentials are not used in CI.
- Clean-machine Windows installation and first launch require target-environment validation.
- Browser E2E covers the critical onboarding/execution path; additional recovery and multi-step journeys can be added without changing the runtime contract.
