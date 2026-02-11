# Keystroke Simulator - Claude Code Context

## Project Overview

Python desktop automation tool (v3.0) that captures screen regions, watches for pixel/region changes, and replays predefined keystroke sequences. Primarily designed for macOS (PyObjC) with Windows support (win32 APIs).

## Architecture

### Core Components

1. **Main Application (`keystroke_simulator_app.py`)**
   - Tkinter-based GUI
   - Process selection and monitoring
   - Profile management
   - Event lifecycle coordination
   - State-safe start/stop toggle (only sets `is_running` on successful start)

2. **Event Processing (`keystroke_processor.py`)**
   - Runtime engine: builds mega_rect bounding box, performs pixel or region matching
   - 5-stage main loop pipeline:
     1. Collect raw match states (pixel/region)
     2. Resolve effective states (apply condition chains with DFS cycle detection)
     3. Update `current_states` (thread-safe)
     4. Filter active candidates by conditions
     5. Apply group priority, then execute keystrokes
   - Supports inverted matching (`invert_match`: trigger on mismatch)
   - Region matching with 5-checkpoint verification
   - Independent thread loop for `independent_thread` events (bypasses group/condition logic)
   - Handles timing, randomization, and modifier keys

3. **Profile System (`keystroke_profiles.py`)**
   - Filesystem-backed profile manager using Pickle
   - Stores profiles in `profiles/*.pkl`
   - Supports favorites, copy, and delete operations
   - Auto-creates "Quick" profile
   - **Auto-save** with 250ms debounce (`_schedule_autosave`)
   - Event rename auto-updates condition references across all events
   - Integrated graph viewer (opens/reuses `ProfileGraphViewer` window)

4. **Event Editors**
   - `keystroke_event_editor.py`: Full editor with Korean UI
     - 3 tabs: 기본 (Basic), 상세 설정 (Detail), 조건/그룹 (Conditions/Groups)
     - Condition chain editor with click-to-cycle state (무시 → 활성 필요 → 비활성 필요)
     - DFS-based circular dependency detection
     - Matching mode: 픽셀 (1px) / 영역 (Area) with invert option
     - Group/priority controls, execution type toggles
     - Fixed window size after layout
   - `keystroke_quick_event_editor.py`: Lightweight overlay for quick captures (ALT to move, CTRL to grab)

5. **Screen Capture (`keystroke_capturer.py`)**
   - Uses `mss` to capture 100x100 pixel regions
   - Provides live preview for Quick Event capture

6. **Settings & Models**
   - `keystroke_settings.py`: Settings dialog and JSON serialization
   - `keystroke_models.py`: Dataclasses for profiles, events, and settings
   - `keystroke_modkeys.py`: Modifier key configuration

### Event Model Key Fields

| Field | Type | Description |
|-------|------|-------------|
| `match_mode` | `str` | `"pixel"` (default) or `"region"` |
| `invert_match` | `bool` | Trigger on mismatch instead of match |
| `region_size` | `Tuple[int,int]|None` | Area size for region matching |
| `execute_action` | `bool` | `False` = condition-only event (no key press) |
| `group_id` | `str|None` | Group ID for mutual exclusion |
| `priority` | `int` | Group priority (lower = higher priority) |
| `conditions` | `Dict[str,bool]` | Map of event names to expected states |
| `independent_thread` | `bool` | Run in separate thread, bypass group/condition |

### Supporting Modules

- `keystroke_utils.py`: OS abstractions, process enumeration, hotkey detection
- `keystroke_sounds.py`: Pygame-based audio cues (graceful degradation when no audio hardware)
- `keystroke_sort_events.py`: Event reordering UI
- `keystroke_event_importer.py`: Cross-profile event migration
- `keystroke_event_graph.py`: Component/level-based event dependency graph visualization (PIL-based)
  - Directed acyclic graph from conditions
  - Topological level assignment with barycentric layer optimization
  - Independent component detection and horizontal assembly
  - Bezier edge curves, group backgrounds, badge system (independent/missing/disabled/condition)
  - Cache with hash-based invalidation

### Entry Points

- `main.py`: Standard GUI launcher
- `main_secure.py`: Authentication-gated launcher
- `_local_test_server.py`: Local auth API simulator
- `_lambda.py`: AWS Lambda auth helper

## Key Technologies

- **Python**: 3.13
- **GUI**: Tkinter (Korean UI)
- **Screen Capture**: mss, numpy
- **Vision**: Pixel matching (exact 1px) + Region matching (5-checkpoint) via numpy
- **Input Automation**: pynput, PyObjC (macOS), pywin32 (Windows)
- **Graph Visualization**: Pillow (PIL)
- **Data**: Pickle for profiles, JSON for settings
- **Audio**: Pygame
- **Logging**: loguru
- **Build**: PyInstaller (single executable)

## Important Patterns

### Thread Safety
- The processor runs in a separate thread
- Independent events run in their own threads
- UI updates must be coordinated via the main thread
- `current_states` updates are thread-safe
- Process monitoring happens asynchronously

### Condition Chain Resolution
- Recursive DFS with cycle detection
- "Strict chain" semantics within same loop iteration
- Distinguishes raw pixel match state from effective activation state
- Condition-only events (`execute_action=False`) participate in chains without triggering keys

### Group Priority
- Events with same `group_id` are mutually exclusive
- Lowest `priority` value wins within a group
- Independent thread events bypass group logic entirely

### OS Abstraction
- `keystroke_utils.py` provides unified interface for macOS/Windows
- PyObjC used for macOS window management and input
- win32 APIs used for Windows equivalents

### Data Flow
1. User captures events (pixels + keys) via Quick Event or Event Editor
2. Events stored in Profile (Pickle), auto-saved with 250ms debounce
3. Processor loads profile, builds mega_rect bounding box covering all event positions
4. Runtime: captures mega_rect once per loop, checks pixel/region matches → evaluates conditions → applies group priority → triggers keystroke sequences

## File Locations

- **Profiles**: `profiles/*.pkl`
- **Settings**: `user_settings.json`, `user_settings*.b64` (encrypted backups)
- **App State**: `app_state.json`
- **Logs**: `logs/`
- **Sounds**: Embedded as base64 in `keystroke_sounds.py`
- **Tests**: `tests/`, `run_tests.py`

## Code Style Notes

- Heavy use of dataclasses (`keystroke_models.py`)
- Tkinter event-driven architecture
- OS-specific code isolated in `keystroke_utils.py`
- Settings serialized to JSON with base64 backups
- UI labels/messages in Korean

## Common Tasks

### Adding a New Event Field
1. Update `EventModel` in `keystroke_models.py`
2. Update event editor UI in `keystroke_event_editor.py`
3. Update processor logic in `keystroke_processor.py`
4. Update event_data conversion (processor's data dict building)
5. Ensure Pickle compatibility or handle migration
6. Add tests in `tests/`

### Adding a New Setting
1. Add to `UserSettings` in `keystroke_models.py`
2. Add UI controls in `keystroke_settings.py`
3. Update JSON serialization in settings save/load

### Platform-Specific Features
- Check `keystroke_utils.py` for existing OS detection patterns
- Use `platform.system()` to branch logic
- Test on both macOS and Windows if possible

## Security Features (main_secure.py)

- Device authentication against remote service
- Encrypted local settings and profile metadata
- Session token management
- Failed attempt cooldown logic
- Uses `.env` for `AUTH_URL` and `VALIDATE_URL`

## Testing

- Run tests: `python run_tests.py` (cross-platform)
- Test files in `tests/`:
  - `test_condition_and_core_logic.py`: Condition filtering, group priority, evaluate_and_execute
  - `test_invert_condition_chain.py`: Inverted matching with condition chains, parent/child dependencies
  - `test_check_match.py`: Pixel/region matching, inverted matching, edge cases
  - `test_event_data_conversion.py`: EventModel → event_data conversion, mega_rect calculation
- Use `_local_test_server.py` for auth testing without remote server
- Test pixel matching with different screen resolutions
- Verify thread safety when modifying processor logic

## Debugging

- Check `logs/` for runtime errors
- Use loguru for structured logging
- Process selection issues: check OS permissions for accessibility/screen recording

## Performance

- Mega_rect bounding box computed at startup to minimize capture area
- Screen capture runs continuously during Quick Event mode
- Independent thread events capture their own individual rects
- Consider performance when adding frequent polling logic

## Common Issues

1. **Process not found**: Refresh process list or check OS permissions
2. **Pixel matching fails**: Recapture events or check screen resolution changes
3. **Keys not working**: Verify target process is focused and accepts input
4. **Auth failures**: Check `.env` configuration and network connectivity
5. **Circular conditions**: Editor detects cycles via DFS; restructure condition chain

## Dependencies

- **Core**: mss, numpy, pillow, pynput, pygame, loguru, screeninfo
- **macOS**: pyobjc (v11.1, 100+ framework packages)
- **Windows**: pywin32 (manual install)
- **GUI**: Tkinter (bundled with Python on macOS/Linux)
- **Build**: PyInstaller

## Build & Distribution

- `_build.py`: PyInstaller build script (`--onefile --noconsole --clean --noupx`)
  - Output: `main_secure_v3.0` (single executable)
  - Embeds `.env` variables (AUTH_URL, VALIDATE_URL) into temp script
- `_timestamp.py`: Version/build timestamp utilities
- `_update_sound.py`: Sound asset update utility
- `requirements.txt`: All Python dependencies
- `MANUAL.md`: User-facing documentation

## Git Workflow

- Main branch: `main`
- Worktrees: `main` (primary), `gallant-newton` (at `~/.claude-worktrees/KeystrokeSimulator/gallant-newton`)
- Feature branches: `busy-maxwell`, `gallant-newton`
