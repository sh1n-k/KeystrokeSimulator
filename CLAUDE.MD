# Keystroke Simulator

Python desktop automation tool (v3.0): captures screen regions, watches for pixel/region changes, replays keystroke sequences. macOS primary (PyObjC), Windows support (win32).

## Commands
- (Recommended) Activate venv: `source .venv/bin/activate`
- Run: `python main.py` (GUI) / `python main_secure.py` (auth-gated)
- Test: `python run_tests.py`
- Build: `python _build.py` (PyInstaller single executable)
- Auth test server: `python _local_test_server.py`

If you prefer not to activate venv, use explicit interpreter paths:
- Run: `./.venv/bin/python main.py`
- Test: `./.venv/bin/python run_tests.py`
- Build: `./.venv/bin/python _build.py`

## Architecture

```
main.py                         # Entry point (GUI)
main_secure.py                  # Entry point with auth gate
app/ui/simulator_app.py         # Main Tkinter app
app/core/processor.py           # Core 5-stage pipeline
app/core/models.py              # Dataclasses: EventModel, ProfileModel, UserSettings
app/ui/event_editor.py          # Full event editor dialog
app/ui/quick_event_editor.py    # Quick event creation dialog
app/ui/event_importer.py        # Import events between profiles
app/ui/event_graph.py           # Condition chain graph visualization
app/core/capturer.py            # Screen capture thread
app/storage/profile_storage.py  # Profile JSON serialization + legacy pkl migration
app/ui/profiles.py              # Profile manager/editing flow
app/storage/profile_display.py  # Profile combobox display formatting
app/ui/settings.py              # Settings dialog
app/ui/sort_events.py           # Drag-and-drop event reordering
app/ui/modkeys.py               # Modification keys config window
app/utils/sounds.py             # Start/stop sound playback
app/utils/system.py             # Shared system utilities
app/utils/i18n.py               # Localization helpers
app/utils/runtime_toggle.py     # Runtime toggle helpers
app/compat/legacy.py            # Legacy module-name mapping source of truth
_build.py                       # PyInstaller build script
_lambda.py                      # AWS Lambda auth backend (server-side only)
_local_test_server.py           # Local auth test server
tests/                          # unittest test suite
```

### Canonical Imports
- Internal code and tests must import from `app.*`.
- Root-level modules such as `keystroke_*.py`, `i18n.py`, `profile_display.py`, and `runtime_toggle_*.py` are compatibility shims only.
- If backward compatibility changes, update `app/compat/legacy.py`, the root shim, build hidden imports, and legacy pickle loading in the same change.

### 5-Stage Processor Pipeline (`app/core/processor.py`)
1. Collect raw match states (pixel/region)
2. Resolve effective states (condition chains with DFS cycle detection)
3. Update `current_states` (thread-safe)
4. Filter active candidates by conditions
5. Apply group priority, then execute keystrokes

### Key Patterns
- **Thread Safety**: Processor runs in separate thread. Independent events get own threads. UI updates via main thread only.
- **Condition Chains**: Recursive DFS with cycle detection. "Strict chain" within same loop iteration. Distinguishes raw match state vs effective activation state. Condition-only events (`execute_action=False`) participate in chains without triggering keys.
- **Group Priority**: Same `group_id` = mutually exclusive. Lower `priority` value wins. Independent thread events bypass group logic.
- **Inverted Matching**: `invert_match=True` triggers on mismatch.
- **Region Mode Matching**: At init, `held_screenshot` + `clicked_position` + `region_size` → extract reference image → sample N dynamic grid checkpoints (5–25, proportional to ROI area: `n = max(5, min(25, area // 100))`), laid out as a uniform cols×rows grid (corners always included, duplicates removed). At runtime, extract ROI from mega_rect capture centered at `(rel_x, rel_y)` with `region_w × region_h`, then compare each checkpoint color with `np.array_equal`. All checkpoints must match. `ref_pixel_value` is unused in region mode.
- **Capture Size vs Region Size**: `ScreenshotCapturer.box_w/box_h` (UI "캡처 크기", basic tab) = live preview capture area. `EventModel.region_size` (UI "영역 크기", detail tab) = matching ROI size used by processor. These are independent; if capture area < region_size the ROI extraction returns `None` → no match.

### Data Flow
Capture events → Profile (JSON, 250ms debounce auto-save) → Processor builds mega_rect → Runtime loop: capture → match → conditions → group priority → keystrokes

## Common Tasks

### Adding a New Event Field
1. `app/core/models.py`: Update `EventModel` dataclass
2. `app/ui/event_editor.py`: Add UI controls
3. `app/core/processor.py`: Add processing logic + event_data conversion
4. Ensure JSON schema compatibility (`schema_version`) or handle migration (legacy `profiles/*.pkl` import may exist)
5. Add tests in `tests/`

### Adding a New Setting
1. `app/core/models.py`: Add to `UserSettings`
2. `app/ui/settings.py`: Add UI controls + JSON serialization

## File Locations
- Profiles: `profiles/*.json` (legacy `profiles/*.pkl` may exist)
- Settings: `user_settings.json`
- Logs: `logs/`
- Auth config: `.env` (`AUTH_URL`, `VALIDATE_URL`)

## Tech Stack
Python 3.13, Tkinter (Korean UI), mss + numpy (capture/vision), pynput + PyObjC/pywin32 (input), Pillow (graph/visualization), Pygame (audio), screeninfo (monitor detection), requests + python-dotenv (auth), loguru (logging)

## Testing
- Framework: `unittest`
- Run: `python run_tests.py` (auto-discovers `tests/test_*.py`)
- Import rule guard: `tests/test_import_conventions.py` blocks new internal imports of legacy root shims
- Test areas: condition chains, check_match, event data conversion, invert conditions, event graph algorithms, ROI extraction, resolve effective states, profile display, profile JSON storage, capture size (`set_capture_size`)

## Git Workflow
- Main branch: `main`

## Known Constraints
- Profiles use JSON (`app/storage/profile_storage.py`): legacy `.pkl` files auto-converted on load. `PROFILE_SCHEMA_VERSION` tracks schema changes.
- macOS: requires Accessibility + Screen Recording permissions
- `_lambda.py` is AWS Lambda server-side code, not part of the client app

## Debugging
- Logs: `logs/`
- OS permissions issue → check accessibility/screen recording permissions
