# AGENTS.md

## Project overview

KeystrokeSimulator is a Python/Tkinter desktop automation app that watches screen pixels/regions and executes predefined keystroke sequences when conditions match. macOS (PyObjC) is the primary target; Windows is supported via win32 tooling.

Primary goals for agents:
- Keep `main.py` / `app/ui/simulator_app.py` runnable.
- Keep the event processing pipeline in `app/core/processor.py` correct (conditions, groups, inversion, threading).
- Maintain backward compatibility for saved profiles (`profiles/*.json` primary; legacy `profiles/*.pkl` may exist and should migrate cleanly).
- Prefer the package layout under `app/` for new work; root-level legacy module names now exist only as compatibility shims for older imports, tests, scripts, and pickle migration paths.

## Setup commands

Requirements:
- `uv` 0.7+ and Python 3.13 with Tk/Tcl available.

Sync the default environment:
```bash
uv python install 3.13
uv sync
```

Run commands inside the managed environment:
```bash
uv run python main.py
```

Notes:
- Dependencies are managed in `pyproject.toml`; platform-specific packages are selected with environment markers.
- Windows: close the running GUI before recreating `.venv` or re-syncing, because Python/DLL files may be locked.
- macOS: the app typically requires Accessibility and Screen Recording permissions for input/capture.
- Dependency source of truth is `pyproject.toml` with `uv.lock`.

## Run commands

Run the GUI:
```bash
uv run python main.py
```

Run the auth-gated GUI:
```bash
uv run python main_secure.py
```

Local auth test server:
```bash
uv run python _local_test_server.py
```

Auth configuration:
- `main_secure.py` loads `.env` (via `python-dotenv`) and uses `AUTH_URL` and `VALIDATE_URL`.
- Do not commit `.env` or real service URLs/tokens.

## Test commands

Run unit tests (`unittest` discovery under `tests/`):
```bash
uv run python run_tests.py
```

Quieter output:
```bash
uv run python run_tests.py -q
```

If you need to force a specific interpreter:
```bash
uv run python run_tests.py --python <path-to-python>
```

Run GUI-including tests (when display/Tk environment is available):
```bash
RUN_GUI_TESTS=1 uv run python run_tests.py --python <path-to-python> -q
```

## Build commands

Build uses PyInstaller from the `build` dependency group:
```bash
uv sync --group build
uv run python _build.py
```

Important safety note:
- `_build.py` rewrites `main_secure.py` by replacing `os.getenv(...)` occurrences with the current process environment values before running PyInstaller.
- Ensure you are not leaking secrets (or unset sensitive env vars) before building.

## Project structure

Key entry points:
- `main.py`: standard GUI entry point (creates `logs/` and `profiles/` if missing).
- `main_secure.py`: GUI entry point with authentication flow (`.env`-based).

Current module layout:
- `app/ui/simulator_app.py`: main Tkinter app and UI flow.
- `app/core/processor.py`: capture -> match -> conditions -> group priority -> keystrokes pipeline.
- `app/storage/profile_storage.py`: JSON/pickle-backed profile persistence and migration.
- `app/utils/runtime_toggle.py`: runtime toggle normalization and validation helpers.
- `app/utils/sounds.py`: runtime sound playback wrapper.
- `app/core/models.py`: dataclasses (events/profiles/settings).
- `app/core/capturer.py`: screen capture thread (mss + screeninfo).
- `app/storage/profile_display.py`: profile dropdown display-label helpers (favorite prefix, Quick exception).
- `app/ui/event_graph.py`: condition graph rendering and layout helpers.
- `app/ui/event_importer.py`: event import dialog and copy helpers.
- `app/ui/modkeys.py`: modification-keys dialog.
- `app/ui/quick_event_editor.py`: quick-event editor dialog.
- `app/ui/settings.py`: settings dialog and persistence UI.
- `app/ui/sort_events.py`: event sort/reorder window.
- `app/utils/i18n.py`: localization helpers.
- `app/utils/system.py`: WindowUtils/KeyUtils/StateUtils/PermissionUtils and related system helpers.
- `app/utils/sound_assets.py`: embedded runtime-toggle sound constants.

Compatibility shims:
- Root-level modules such as `keystroke_simulator_app.py`, `keystroke_profiles.py`, `keystroke_event_editor.py`, `keystroke_processor.py`, `keystroke_profile_storage.py`, `keystroke_utils.py`, `i18n.py`, and related `keystroke_*.py` files now forward to their canonical `app/` modules.
- New code should import from `app.*`; use root-level names only when intentionally preserving external compatibility.

Tests:
- `tests/`: `unittest` suite (`test_*.py`).
- `tests/test_profile_display.py`: favorite profile display-label rules.

Local state (gitignored; avoid relying on these being versioned):
- `profiles/`: saved profiles (`*.json` primary; legacy `*.pkl` may exist).
- `logs/`: log files.
- `*.json`, `*.b64`: user/state artifacts (see `.gitignore`).

## Conventions

Profile persistence:
- Profiles are persisted as JSON (`profiles/*.json`) with `schema_version` and Base64-encoded PNG images for `held_screenshot` (see `app/storage/profile_storage.py`).
- `latest_screenshot` is not persisted; the left preview in the editor is always live capture.
- Legacy Pickle profiles (`profiles/*.pkl`) may exist; loaders should be able to read them and (when loading for real use) migrate to JSON without breaking old data.
- New/fallback profiles should get default `modification_keys` with `alt`/`ctrl`/`shift` enabled and `Pass` mode.

Profile dropdown/UI naming:
- Favorite profiles in the main dropdown may use decorated display labels (for example `⭐ <name>`), while `Quick` remains undecorated and pinned first.
- Always keep internal operations (`load_profile`, copy/delete, state save/load) on canonical profile names, not decorated display labels.

Threading/UI:
- Tkinter UI must remain on the main thread.
- The processor and some events may run in separate threads; be careful with shared state and UI updates.

Processor/auth behavior that should not regress:
- Main-loop activation logic should stay centered on `_resolve_effective_states` (strict condition-chain resolution); avoid reintroducing unused condition-filter helpers.
- In `main_secure.py`, keep lockout countdown single-sourced: `lock_inputs()` should only disable inputs, and `show_error_and_reactivate()` should start `start_countdown(...)` exactly once.

Localization (EN/KO):
- UI text should use `app/utils/i18n.py` helpers (`txt`, `set_language`, `normalize_language`) instead of hard-coded single-language strings.
- Default language is English (`en`). Korean (`ko`) is supported.
- `UserSettings.language` is persisted in `user_settings.json` and loaded by app/settings/auth UI flows.
- For button text that can clip in different languages, use `dual_text_width(...)` instead of fixed widths where practical.
- New/updated tests that assert UI strings should explicitly set language (`set_language("en")` or `set_language("ko")`) before assertions.

## Safety / security boundaries

- Do not commit directly to the default branch (`main`/`master`); use feature branches.
- Do not add secrets, tokens, or real internal URLs to the repo or logs.
- Ask before running destructive commands or making broad refactors/renames.
- Avoid committing generated artifacts or local user files (check `.gitignore`).
