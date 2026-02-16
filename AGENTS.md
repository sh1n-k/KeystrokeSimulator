# AGENTS.md

## Project overview

KeystrokeSimulator is a Python/Tkinter desktop automation app that watches screen pixels/regions and executes predefined keystroke sequences when conditions match. macOS (PyObjC) is the primary target; Windows is supported via win32 tooling.

Primary goals for agents:
- Keep `main.py` / `keystroke_simulator_app.py` runnable.
- Keep the event processing pipeline in `keystroke_processor.py` correct (conditions, groups, inversion, threading).
- Maintain backward compatibility for saved profiles (`profiles/*.json` primary; legacy `profiles/*.pkl` may exist and should migrate cleanly).

## Setup commands

Requirements:
- Python 3.13 (venv recommended) with Tk/Tcl available.

Create and use a venv:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies (macOS-focused `requirements.txt`):
```bash
pip install -r requirements.txt
```

Notes:
- Windows: `requirements.txt` includes `pyobjc*` packages. You will likely need to skip/remove those and install `pywin32` separately.
- macOS: the app typically requires Accessibility and Screen Recording permissions for input/capture.

## Run commands

Run the GUI:
```bash
python3 main.py
```

Run the auth-gated GUI:
```bash
python3 main_secure.py
```

Local auth test server:
```bash
python3 _local_test_server.py
```

Auth configuration:
- `main_secure.py` loads `.env` (via `python-dotenv`) and uses `AUTH_URL` and `VALIDATE_URL`.
- Do not commit `.env` or real service URLs/tokens.

## Test commands

Run unit tests (`unittest` discovery under `tests/`):
```bash
python3 run_tests.py
```

Quieter output:
```bash
python3 run_tests.py -q
```

If you need to force a specific interpreter:
```bash
python3 run_tests.py --python .venv/bin/python
```

## Build commands

Build uses PyInstaller (not pinned in `requirements.txt`):
```bash
pip install pyinstaller
python3 _build.py
```

Important safety note:
- `_build.py` rewrites `main_secure.py` by replacing `os.getenv(...)` occurrences with the current process environment values before running PyInstaller.
- Ensure you are not leaking secrets (or unset sensitive env vars) before building.

## Project structure

Key entry points:
- `main.py`: standard GUI entry point (creates `logs/` and `profiles/` if missing).
- `main_secure.py`: GUI entry point with authentication flow (`.env`-based).

Core modules:
- `keystroke_simulator_app.py`: main Tkinter app and UI flow.
- `keystroke_processor.py`: capture -> match -> conditions -> group priority -> keystrokes pipeline.
- `keystroke_models.py`: dataclasses (events/profiles/settings).
- `profile_display.py`: profile dropdown display-label helpers (favorite prefix, Quick exception).
- `keystroke_capturer.py`: screen capture thread (mss + screeninfo).

Tests:
- `tests/`: `unittest` suite (`test_*.py`).
- `tests/test_profile_display.py`: favorite profile display-label rules.

Local state (gitignored; avoid relying on these being versioned):
- `profiles/`: saved profiles (`*.json` primary; legacy `*.pkl` may exist).
- `logs/`: log files.
- `*.json`, `*.b64`: user/state artifacts (see `.gitignore`).

## Conventions

Profile persistence:
- Profiles are persisted as JSON (`profiles/*.json`) with `schema_version` and Base64-encoded PNG images for `held_screenshot` (see `keystroke_profile_storage.py`).
- `latest_screenshot` is not persisted; the left preview in the editor is always live capture.
- Legacy Pickle profiles (`profiles/*.pkl`) may exist; loaders should be able to read them and (when loading for real use) migrate to JSON without breaking old data.
- New/fallback profiles should get default `modification_keys` with `alt`/`ctrl`/`shift` enabled and `Pass` mode.

Profile dropdown/UI naming:
- Favorite profiles in the main dropdown may use decorated display labels (for example `⭐ <name>`), while `Quick` remains undecorated and pinned first.
- Always keep internal operations (`load_profile`, copy/delete, state save/load) on canonical profile names, not decorated display labels.

Threading/UI:
- Tkinter UI must remain on the main thread.
- The processor and some events may run in separate threads; be careful with shared state and UI updates.

## Safety / security boundaries

- Do not commit directly to the default branch (`main`/`master`); use feature branches.
- Do not add secrets, tokens, or real internal URLs to the repo or logs.
- Ask before running destructive commands or making broad refactors/renames.
- Avoid committing generated artifacts or local user files (check `.gitignore`).
