### **1. Project Overview**

#### **Core Purpose and Features**
This project is a **user authentication-based keystroke automation tool**. Its main features are:
- **User Authentication & Session Management**: Utilizes a server-client architecture with AWS Lambda and DynamoDB to authenticate users and issue/validate session tokens, ensuring only authorized users can operate the program. (`main_secure.py`, `_lambda.py`)
- **Screen Recognition & Keystroke Automation**: Detects the pixel color at user-specified screen coordinates. If the condition is met, it automatically inputs a pre-configured key. This core logic runs asynchronously in a separate thread to maintain GUI responsiveness. (`keystroke_processor.py`)
- **Profile-Based Event Management**: Multiple keystroke automation rules (events) can be saved and managed as 'profiles'. Users can create, edit, copy, delete, and import events through the GUI. (`keystroke_profiles.py`, `keystroke_event_editor.py`)
- **Telegram Notifications**: Sends notifications to an administrator via a Telegram bot for events like user authentication success, failure, or errors. (`_lambda.py`)

#### **Primary Users/Target Audience**
This tool is intended for users who want to automate repetitive tasks in GUI-based applications, especially games. The primary users are those capable of configuring automation logic themselves, as they need to define which key to press under specific conditions (e.g., when a certain icon appears on screen).

#### **Project Scale and Complexity**
- **Scale**: Medium. This is more than a simple algorithm script; it's a multi-module project that includes a desktop GUI application, client-server communication, a cloud backend (AWS Lambda, DynamoDB), and build scripts for executables.
- **Complexity**: Medium-High. The project incorporates several complex technical elements:
    - **GUI Programming**: Multi-window and complex widget management using `tkinter`.
    - **Concurrency**: Simultaneous use of `threading` to prevent GUI freezing and `asyncio` for efficient core logic processing.
    - **Platform Dependency Handling**: Code branches that call different APIs depending on the operating system (Windows or macOS). (`keystroke_utils.py`, `keystroke_processor.py`)
    - **Image Processing**: Fast screen capture with `mss` and image analysis with `Pillow`.
    - **Data Clustering**: Uses `scikit-learn`'s DBSCAN algorithm to cluster multiple detection points on the screen and optimize the capture area. (`keystroke_processor.py`)
    - **Security & Authentication**: User authentication and session management via a server (AWS Lambda).

### **2. Technology Stack Analysis**

- **Language**: Python 3
- **Framework**:
    - `tkinter`: For the desktop GUI.
- **Key Libraries**:
    - `requests`: To call the server API (Lambda). (`main_secure.py`)
    - `loguru`: For file logging and log rotation.
    - `mss`, `Pillow`, `screeninfo`: For screen capture and image processing.
    - `numpy`, `scikit-learn`: For event coordinate clustering.
    - `keyboard`, `pynput`: For cross-platform global keyboard/mouse event detection.
    - `pygame`: To play start/stop sound effects. (`keystroke_sounds.py`)
    - `boto3`: To control AWS services (DynamoDB). (`_lambda.py`)
    - `python-dotenv`: For managing environment variables.
- **Database**: AWS DynamoDB (for user, session, and authentication log tables)
- **Infrastructure**: AWS Lambda (serverless backend logic), Amazon API Gateway (implicitly used to expose Lambda as an HTTP API)
- **Development/Deployment Tools**:
    - `PyInstaller`: To package Python scripts into a single executable file (.exe). (`_build.py`)

### **3. Architectural Structure**

#### **3.1. Project Structure**

The project can be logically grouped by role as follows:

**Entry Point & Core Application**
*   `main.py`: **Role & Function**: A development entry point that sets up logging and runs `KeystrokeSimulatorApp` directly without security authentication.
*   `main_secure.py`: **Role & Function**: The end-user entry point that includes security authentication. It first performs user authentication via `AuthUI`, and upon success, launches `KeystrokeSimulatorApp`.
*   `keystroke_simulator_app.py`: **Role & Function**: Creates and manages the main application GUI window. It acts as the central hub, handling process/profile selection, start/stop controls, and launching various settings windows.

**Backend (AWS Lambda)**
*   `_lambda.py`: **Role & Function**: The server-side code that runs on AWS Lambda. It handles all backend logic, including user authentication, session validation, admin functions (user management, log cleanup), and sending Telegram notifications. It interacts directly with DynamoDB.

**Core Logic (Automation Engine)**
*   `keystroke_processor.py`: **Role & Function**: The core engine for pixel detection and keystroke automation. It runs asynchronously in a separate thread and contains logic for event coordinate clustering, screen capture, image analysis, and key input simulation.

**Data Models**
*   `keystroke_models.py`: **Role & Function**: Defines the core data structures used in the project, such as `UserSettings`, `EventModel`, and `ProfileModel`, using `dataclasses`. These models are serialized via `pickle` for saving/loading profiles.

**GUI Modules (Settings Windows)**
*   `keystroke_profiles.py`: **Role & Function**: Manages the 'Profile Manager' window. Allows users to view the list of events within a profile and edit, add, or import events.
*   `keystroke_event_editor.py`: **Role & Function**: Manages the 'Event Settings' window. Provides a complex UI for configuring the details of a single event (detection area, reference pixel, input key, press duration, etc.).
*   `keystroke_quick_event_editor.py`: **Role & Function**: Manages the 'Quick Events' window. Provides a simplified UI for quickly creating events using keyboard/mouse shortcuts and saving them to the 'Quick.pkl' profile.
*   `keystroke_event_importer.py`: **Role & Function**: Provides the 'Import events' window for importing events from another profile into the current one.
*   `keystroke_sort_events.py`: **Role & Function**: Manages the 'Event Organizer' window. Allows users to reorder events within a profile via drag-and-drop.
*   `keystroke_settings.py`: **Role & Function**: Manages the 'Settings' window for global settings like start/stop hotkeys and key input delays.
*   `keystroke_modkeys.py`: **Role & Function**: Manages the 'Modification Keys' window, allowing users to configure behavior when modifier keys (Alt, Ctrl, Shift) are pressed on a per-profile basis.

**Utilities & Helpers**
*   `keystroke_utils.py`: **Role & Function**: A collection of utility functions and classes used across multiple modules (`WindowUtils`, `KeyUtils`, `StateUtils`, `ProcessUtils`). Contains OS-specific branching logic.
*   `keystroke_capturer.py`: **Role & Function**: A class that encapsulates the functionality of continuously capturing the screen area around the mouse cursor. Used by `keystroke_event_editor` to show a live view.
*   `keystroke_sounds.py`: **Role & Function**: Provides a `SoundPlayer` class that uses `pygame` to play start and stop sound effects. Sound data is Base64-encoded and embedded in the code.
*   `_timestamp.py`: **Role & Function**: A simple utility script to convert a Unix timestamp to a Korean Time (KTC) string.

**Build & Test**
*   `_build.py`: **Role & Function**: A script that uses `PyInstaller` to build the project into a single executable. It plays a critical role in injecting environment variables from a `.env` file into the code at build time.
*   `_update_sound.py`: **Role & Function**: A utility script to Base64-encode new sound files (.mp3, .wav) and update the sound variables in `keystroke_sounds.py`.
*   `_local_test_server.py`: **Role & Function**: Runs a simple mock authentication server to test the authentication logic locally without needing the actual AWS backend.

#### **3.2. Data Flow and Dependencies**
1.  **Execution & Authentication**: `main_secure.py` runs → `AuthUI` prompts for ID → An authentication request is sent to `_lambda.py` → DynamoDB is checked, and a session token is issued → The token is saved on the client.
2.  **Profile Loading**: User selects a profile in the GUI → The corresponding `.pkl` file is loaded from the `profiles/` folder → It's converted into a `ProfileModel` object.
3.  **Automation Start**: User clicks the 'Start' button → `KeystrokeSimulatorApp` passes the list of events from the `ProfileModel` to the `KeystrokeProcessor` thread and starts it.
4.  **Automation Loop**: `KeystrokeProcessor` captures the screen → analyzes the image → simulates a keystroke if conditions are met.
5.  **Settings Saving**: When events or settings are changed via the GUI, they are updated in `EventModel`, `ProfileModel`, or `UserSettings` objects, which are then serialized to disk as `.pkl` or `.b64` files.

### **4. Core Code Patterns**

-   **Coding Style and Conventions**: Generally adheres to PEP 8, uses `dataclasses` for clear model definitions, and features structured logging with `loguru`.
-   **Key Design Patterns**:
    -   **Threading**: The time-consuming `KeystrokeProcessor` task is separated into its own thread to maintain UI responsiveness.
    -   **Callback**: Callback functions are widely used to handle GUI button events and post-task actions.
    -   **Model-View-Controller (MVC, Loose)**: `keystroke_models.py` acts as the Model, the `tkinter` UI classes are the View, and the event handler methods within the UI classes serve as the Controller.
-   **Error Handling Methods**:
    -   `try...except` blocks are used to handle potential exceptions from file I/O, network requests, and API calls.
    -   The server (`_lambda.py`) catches `ClientError` to handle specific DynamoDB errors (e.g., conditional write failures) and implements an exponential backoff retry logic for `ProvisionedThroughputExceededException`.
    -   User-facing errors are displayed using `tkinter.messagebox`.

### **5. Development Context**

-   **Configuration Files and Environment Variables**:
    -   `user_settings.b64`: A Base64-encoded JSON file containing user settings like key press duration and loop delay.
    -   `app_state.json`: Stores the last used window position, profile, etc., to restore the state on the next launch.
    -   `.env`: Stores sensitive information like the AWS Lambda URL, Telegram Bot Token, and DynamoDB table names. **This information is hardcoded into the executable at build time by the `_build.py` script.**
-   **Build/Deployment Process**:
    -   The `_build.py` script uses `PyInstaller` to create a single executable file.
    -   During this process, it creates a temporary Python file where `os.getenv()` calls are replaced with their actual environment variable values. This allows the executable to be deployed with the configuration embedded, without needing the `.env` file.
-   **Test Structure**:
    -   `_local_test_server.py` acts as a simple mock server, enabling the client's authentication logic to be tested without a live AWS Lambda instance.

### **6. Metadata for LLM Support**

-   **Frequently Modified Files**:
    -   `keystroke_processor.py`: For core automation logic (performance improvements, new detection methods).
    -   `_lambda.py`: For backend logic changes (user management, authentication policies).
    -   `keystroke_event_editor.py` / `keystroke_profiles.py`: For UI modifications, such as adding new settings to events.
    -   `keystroke_models.py`: The first file to be modified when adding new data fields to profiles or events.
-   **Location of Critical Business Logic**:
    -   **User Authentication**: `AuthService` class in `main_secure.py` and the `/authenticate` route within `lambda_handler` in `_lambda.py`.
    -   **Session Validation**: `validate_session_token` in `main_secure.py` and the `/validate` route in `_lambda.py`.
    -   **Pixel Detection & Key Input**: `_run_processor`, `_capture_and_process_clusters`, and `_simulate_keystroke_sync` methods in the `KeystrokeProcessor` class.
    -   **Event Coordinate Clustering**: `_compute_clusters_and_mega_rect` method in the `KeystrokeProcessor` class.
    -   **Profile/Event Data Management**: `_save_profile` method in `keystroke_profiles.py`, which uses `pickle` for file storage.
    -   **Admin Functions**: Functions routed under `/admin/*` paths in `_lambda.py` (user creation, deletion, etc.).
-   **External API and Service Integrations**:
    -   **AWS Lambda**: Called via `AUTH_URL` and `VALIDATE_URL` defined in `main_secure.py`.
    -   **AWS DynamoDB**: Accessed via the `boto3` library in `_lambda.py` to store and query user, session, and log data.
    -   **Telegram Bot API**: Used in the `send_telegram_message_async` function in `_lambda.py` to send authentication-related notifications.
-   **Known Issues or Constraints**:
    -   **Security**: Since `_build.py` hardcodes environment variables into the executable, there is a risk of exposing internal URLs or API keys if the executable is leaked and reverse-engineered.
    -   **Performance**: Several functions in `_lambda.py` (`list_users`, `cleanup_old_logs`) use DynamoDB `scan` operations, which can lead to performance degradation and increased costs as the tables grow.
    -   **Data Compatibility**: Profiles are saved using `pickle`. If the structure of `EventModel` or `ProfileModel` changes, profile files saved with an older version may become incompatible.
    -   **Platform Dependency**: While aiming to support both Windows and macOS, the use of different libraries and approaches for OS-specific features like global hotkeys can lead to platform-specific bugs.