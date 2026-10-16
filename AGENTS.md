# Repository Guidelines

Only required values belong in `.env`; configurable options belong in the admin UI. Keep code clean without superseded compatibility layers. Use a new branch for major changes. Search GitHub for relevant open-source implementations before starting a task. After completing and verifying changes, automatically commit and push them.

## Project Structure

- `src/` contains the Tauri web UI (`index.html`, `app.js`, `styles.css`).
- `src-tauri/src/` contains the Rust desktop commands, GPU locking, generation workflows, and mobile connection lifecycle.
- `mobile/` contains the FastAPI gateway, local generation runner, PWA assets, and tests in `mobile/tests/`.
- `tools/` contains setup, build, smoke-test, and mobile lifecycle scripts.
- `docs/` documents installation, models, workflows, mobile use, and release procedures.
- Generated images, runtime state, model files, `dist/`, and build output are local-only and should not be committed.

## Build, Test, and Development Commands

Run from the repository root (`D:\codes\qmii_ai`):

```powershell
powershell -ExecutionPolicy Bypass -File tools\setup-workflow.ps1
powershell -ExecutionPolicy Bypass -File tools\verify-models.ps1
cargo check --manifest-path src-tauri\Cargo.toml
powershell -ExecutionPolicy Bypass -File tools\build.ps1
```

Use the bundled environment for Python tests:

```powershell
.runtime\mobile-venv\Scripts\python.exe -m unittest discover -s mobile\tests -v
node tools\test-mobile-ui.cjs
powershell -ExecutionPolicy Bypass -File tools\test-mobile-session.ps1
```

`build.ps1` creates `dist\千迷AI.exe`, a versioned executable, and `SHA256SUMS.txt`. Do not run GPU smoke tests unless the local Qwen Image Turbo runtime and models are installed.

Every completed code or UI change must be packaged as a new version before handoff. Run `tools\build.ps1` after the change, verify that the build succeeds and the updated executable exists in `dist\`, and report the generated versioned artifact. Source-only changes are not considered complete.

## Coding Style and Naming

Use four spaces for Rust and Python, two spaces for JavaScript, and preserve the existing concise browser code style. Use Rust `snake_case`, Python `snake_case`, JavaScript `camelCase`, and descriptive kebab-free filenames. Run `cargo fmt` before Rust changes; keep user-facing text in Traditional Chinese and escape dynamic HTML through the existing helpers.

## Testing Guidelines

Name Python tests `test_*.py` and test methods `test_*`. Add regression coverage for API validation, authentication, and generation argument changes. For UI changes, run the mobile UI smoke test and manually verify the desktop composer when practical.

## Commits and Pull Requests

Recent commits use short Conventional Commit-style prefixes such as `feat:` and `docs:`. Keep commits focused, imperative, and concise. Pull requests should describe user-visible behavior, list validation commands, note model/runtime prerequisites, and include screenshots for UI changes. Never commit credentials, access codes, generated images, model binaries, or runtime logs.
