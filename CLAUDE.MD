# Keystroke Simulator - Claude Code Context

## Project Overview

This is a Python desktop automation tool that captures screen regions, watches for pixel changes, and replays predefined keystroke sequences. The app is primarily designed for macOS (using PyObjC) but supports Windows (using win32 APIs).

## Architecture

### Core Components

1. **Main Application (`keystroke_simulator_app.py`)**
   - Tkinter-based GUI
   - Process selection and monitoring
   - Profile management
   - Event lifecycle coordination

2. **Event Processing (`keystroke_processor.py`)**
   - Runtime engine that clusters reference pixels using DBSCAN
   - Watches for pixel matches in target process windows
   - Issues key presses via OS-specific APIs
   - Handles timing, randomization, and modifier keys

3. **Profile System (`keystroke_profiles.py`)**
   - Filesystem-backed profile manager using Pickle
   - Stores profiles in `profiles/*.pkl`
   - Supports favorites, copy, and delete operations
   - Auto-creates "Quick" profile

4. **Event Editors**
   - `keystroke_event_editor.py`: Full editor for timing, keys, and pixel data
   - `keystroke_quick_event_editor.py`: Lightweight overlay for quick captures (ALT to move, CTRL to grab)

5. **Screen Capture (`keystroke_capturer.py`)**
   - Uses `mss` to capture 100×100 pixel regions
   - Provides live preview for Quick Event capture

6. **Settings & Models**
   - `keystroke_settings.py`: Settings dialog and JSON serialization
   - `keystroke_models.py`: Dataclasses for profiles, events, and settings
   - `keystroke_modkeys.py`: Modifier key configuration

### Supporting Modules

- `keystroke_utils.py`: OS abstractions, process enumeration, hotkey detection
- `keystroke_sounds.py`: Pygame-based audio cues
- `keystroke_sort_events.py`: Event reordering UI
- `keystroke_event_importer.py`: Cross-profile event migration

### Entry Points

- `main.py`: Standard GUI launcher
- `main_secure.py`: Authentication-gated launcher
- `_local_test_server.py`: Local auth API simulator
- `_lambda.py`: AWS Lambda auth helper

## Key Technologies

- **GUI**: Tkinter
- **Screen Capture**: mss, numpy
- **Vision**: DBSCAN clustering (scikit-learn)
- **Input Automation**: pynput, PyObjC (macOS), pywin32 (Windows)
- **Data**: Pickle for profiles, JSON for settings
- **Logging**: loguru

## Important Patterns

### Thread Safety
- The processor runs in a separate thread
- UI updates must be coordinated via the main thread
- Process monitoring happens asynchronously

### OS Abstraction
- `keystroke_utils.py` provides unified interface for macOS/Windows
- PyObjC used for macOS window management and input
- win32 APIs used for Windows equivalents

### Data Flow
1. User captures events (pixels + keys) via Quick Event or Event Editor
2. Events stored in Profile (Pickle)
3. Processor loads profile, clusters pixels using DBSCAN
4. Runtime: watches for matches → triggers keystroke sequences

## File Locations

- **Profiles**: `profiles/*.pkl`
- **Settings**: `user_settings.json`, `user_settings*.b64` (encrypted backups)
- **Logs**: `logs/`
- **Sounds**: `start.mp3`, `stop.mp3`

## Code Style Notes

- Heavy use of dataclasses (`keystroke_models.py`)
- Tkinter event-driven architecture
- OS-specific code isolated in `keystroke_utils.py`
- Settings serialized to JSON with base64 backups

## Common Tasks

### Adding a New Event Field
1. Update `KeystrokeEvent` in `keystroke_models.py`
2. Update event editor UI in `keystroke_event_editor.py`
3. Update processor logic in `keystroke_processor.py`
4. Ensure Pickle compatibility or handle migration

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

## Development Tips

### Testing
- Use `_local_test_server.py` for auth testing without remote server
- Test pixel matching with different screen resolutions
- Verify thread safety when modifying processor logic

### Debugging
- Check `logs/` for runtime errors
- Use loguru for structured logging
- Process selection issues: check OS permissions for accessibility/screen recording

### Performance
- DBSCAN clustering runs per-event at startup
- Screen capture runs continuously during Quick Event mode
- Consider performance when adding frequent polling logic

## Common Issues

1. **Process not found**: Refresh process list or check OS permissions
2. **Pixel matching fails**: Adjust clustering parameters or recapture events
3. **Keys not working**: Verify target process is focused and accepts input
4. **Auth failures**: Check `.env` configuration and network connectivity

## Dependencies Notes

- PyObjC frameworks: Required for macOS, skip on Windows
- pywin32: Required for Windows, skip on macOS
- Tkinter: Bundled with Python on macOS/Linux, check Windows installation
- mss: Cross-platform screenshot library
- scikit-learn: Required for DBSCAN clustering

## Build & Distribution

- `_build.py`: Build script (likely PyInstaller or similar)
- `_timestamp.py`: Version/build timestamp utilities
- `_update_sound.py`: Sound asset update utility
- `requirements.txt`: All Python dependencies

## Git Workflow

- Main branch: `main`
- Current worktree: `gallant-newton`
- Recent commits show ongoing UI/UX improvements and timing logic enhancements
