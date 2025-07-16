# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Running the Application
- **Standard version**: `python main.py`
- **Secure version with authentication**: `python main_secure.py`
- **Local test server**: `python _local_test_server.py` (for testing authentication)

### Dependencies
- Install dependencies: `pip install -r requirements.txt`
- For Windows-specific builds: `pip install -r requirements-win.txt`

### Building Executables
- Build standalone executable: `python _build.py`
- Creates executable with version number (e.g., main_secure_v2.21.exe)
- Uses PyInstaller with --onefile, --noconsole, --clean, --noupx flags
- Automatically replaces environment variables in build

## Architecture Overview

### Core Application Structure
This is a Python-based keystroke automation application built with tkinter for the GUI. The application follows a modular architecture with clear separation of concerns:

**Main Application Flow:**
- `main.py` / `main_secure.py` → `keystroke_simulator_app.py` (main GUI) → individual modules

**Key Components:**
- **Models** (`keystroke_models.py`): Data classes for `ProfileModel`, `EventModel`, and `UserSettings`
- **Profiles** (`keystroke_profiles.py`): Profile management with pickle serialization
- **Events**: Event creation (`keystroke_quick_event_editor.py`), editing (`keystroke_event_editor.py`), and importing (`keystroke_event_importer.py`)
- **Processor** (`keystroke_processor.py`): Process targeting and keystroke execution
- **Utils** (`keystroke_utils.py`): Utility classes for process management, state handling, and window operations

### Authentication System (Secure Version)
- Device-based authentication with encrypted local storage
- Environment variable configuration via .env file
- Server-side validation through REST API endpoints
- Fallback to local test server for development

### Data Storage
- **Profiles**: Stored as pickle files in `profiles/` directory
- **Settings**: Base64 encoded in `user_settings.b64`
- **Application State**: JSON format in `app_state.json`
- **Logs**: Loguru-based logging to `logs/keysym.log` with 1MB rotation

### Key Features
- **Process Targeting**: Select specific applications for keystroke automation
- **Profile Management**: Create, edit, copy, and delete automation profiles
- **Event System**: Individual keystroke events with timing, positioning, and randomization
- **Quick Events**: Rapid setup for common keystroke patterns
- **Sound Feedback**: Audio notifications for start/stop actions via pygame
- **Modifier Keys**: Support for Shift, Ctrl, Alt combinations
- **Screenshot Integration**: Visual reference for click positioning using PIL/mss

### GUI Framework
- Built with tkinter/ttk for cross-platform compatibility
- Modular frame-based components (`ProcessFrame`, `ProfileFrame`, etc.)
- Event-driven architecture with callback patterns
- Thread-safe operations for background keystroke execution

### Development Notes
- Uses `keyboard` library for global hotkey detection and keystroke simulation
- `pynput` for additional input handling capabilities
- Cross-platform support with platform-specific adaptations
- Extensive logging with loguru for debugging and monitoring
- Environment variable support via python-dotenv