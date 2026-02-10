# Keystroke Simulator / 키스트로크 시뮬레이터

[English](#english) | [한국어](#korean)

<a name="english"></a>
## English

A Python desktop automation tool that captures small screen regions, watches for pixel changes, and replays predefined keystroke sequences that you build through a Tkinter GUI. The app focuses on macOS (PyObjC) but shares the same code paths for Windows with a matching win32 environment.

### Table of Contents
- [Features](#features)
- [Project Structure](#project-structure)
- [Requirements](#requirements)
- [Installation](#installation)
- [Usage](#usage)
- [Security Features](#security-features)
- [Contributing](#contributing)
- [License](#license)

<h3 id="features">Features</h3>

- Process selection with live process enumeration so keystrokes only target the correct window.
- Pixel-matching keystroke playback powered by MSS screen grabs and numpy for exact pixel/region comparison.
- Profile management (including a dedicated "Quick" profile) to organize sequences, favorite workflows, and copy/delete variants.
- Quick Event capture tool that records reference pixels directly from the screen (ALT to reposition, CTRL to grab, mouse click to place the crosshair).
- Fine-grained settings for delays, modifier keys, hotkeys, and loop randomization plus audible start/stop cues.
- Optional secure mode (`main_secure.py`) that authenticates devices against a remote service.

<h3 id="project-structure">Project Structure</h3>

The project consists of several Python files, each responsible for different functionalities:

- `_lambda.py`: AWS Lambda helper for device authentication.
- `_local_test_server.py`: Local test harness that mimics the authentication backend.
- `main.py`: Standard entry point that launches the Tkinter app.
- `main_secure.py`: Entry point that injects the authentication flow before opening the main UI.
- `keystroke_simulator_app.py`: Core Tkinter GUI, main loop, process list, listeners, and wiring between modules.
- `keystroke_capturer.py`: Continuously captures a 100×100 pixel box around the cursor via `mss` for Quick Event previews.
- `keystroke_event_editor.py`: Full editor for per-event timing, key selection, and pixel data.
- `keystroke_event_importer.py`: Utilities to migrate events between profiles.
- `keystroke_models.py`: Dataclasses describing profiles, events, and persisted settings.
- `keystroke_modkeys.py`: Configuration window for modifier passthrough and macros.
- `keystroke_processor.py`: Runtime engine that builds a bounding box over all events, performs exact pixel/region matching, and issues key presses via OS-specific APIs.
- `keystroke_profiles.py`: Filesystem-backed profile manager (Pickle persistence plus favorites, copy/delete).
- `keystroke_quick_event_editor.py`: Lightweight overlay for capturing events without leaving the main screen (ALT moves the selector, CTRL saves the current capture).
- `keystroke_settings.py`: Settings dialog plus serialization into `user_settings.json` and base64 backups.
- `keystroke_sort_events.py`: UI for reordering events inside a profile.
- `keystroke_sounds.py`: Simple wrapper around Pygame for start/stop sound cues.
- `keystroke_utils.py`: Shared helpers for window placement, process enumeration, hotkey detection, and OS abstractions (PyObjC on macOS, win32 on Windows).
- Supporting assets: `profiles/` (Pickle files), `logs/`, sound files (`start.mp3`, `stop.mp3`), and base64 backups (`user_settings*.b64`).

<h3 id="requirements">Requirements</h3>

- Python 3.10+ with Tk/Tcl installed (macOS Ventura/Sonoma tested; Windows requires the matching win32 API stack such as `pywin32`).
- Create a virtual environment and install dependencies via `python -m pip install -r requirements.txt`.
- Key third-party packages pulled in by `requirements.txt`:
    - Input/GUI stack: `pynput`, `pygame`, `Pillow`, `screeninfo`.
    - Vision + automation: `mss`, `numpy`, `Cython` (for wheel builds).
    - Infra/utilities: `loguru`, `requests`, `python-dotenv`.
    - macOS support: `pyobjc` (and dozens of system frameworks). These are already listed in `requirements.txt`; skip them on Windows and install `pywin32` manually if you run outside macOS.
- `tkinter` ships with CPython on macOS/Linux. On Windows, ensure it is included with your Python installation.

<h3 id="installation">Installation</h3>

1. Clone the repository:
   ```
   git clone https://github.com/sh1n-k/KeystrokeSimulator.git
   ```
2. Navigate to the project directory:
   ```
   cd KeystrokeSimulator
   ```
3. (Optional but recommended) create a virtual environment:
   ```
   python -m venv .venv
   source .venv/bin/activate  # Windows는 .venv\Scripts\activate
   ```
4. Install dependencies:
   ```
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   ```
5. For the secure build, create a `.env` file with `AUTH_URL` and `VALIDATE_URL`. Local testing can be done via `_local_test_server.py`.

<h3 id="usage">Usage</h3>

1. Run the standard GUI:
   ```
   python main.py
   ```
   To enforce authentication, launch:
   ```
   python main_secure.py
   ```
   The secure flow prompts for a user ID, stores a session token, and only opens the simulator after validation succeeds.

2. Pick the target process via the "Process" combobox (use Refresh to rescan running apps).

3. Choose or create a profile:
   - Profiles live under `profiles/*.pkl`. The default "Quick" profile is auto-created.
   - Use Copy/Delete to manage variations. Favorites bubble to the top of the list.

4. Configure events:
   - **Quick Events**: Opens a live capture window. Use `ALT` to move the capture area, left-click to place the crosshair, press `CTRL` (or the Grab button) to save the current 100×100 screenshot plus key binding into the Quick profile.
   - **Edit Profile**: Full editor for timings, loops, and reference colors.
   - **ModKeys / Sort Profile**: Adjust modifier macros and order of execution.

5. Tune the delays and randomization in **Settings**, including global hotkeys and start/stop triggers.

6. Press **Start**. The processor watches for exact pixel/region matches inside the selected process and sends keystrokes with randomized intervals. Use **Start** again (or configured hotkeys) to stop.

<h3 id="security-features">Security Features</h3>

The secure build (`main_secure.py`) layers an authentication gate before the simulator launches:
- Generates and stores device identifiers in `user_settings*.b64`.
- Encrypts local settings and profile metadata before persisting to disk.
- Talks to the URLs defined in `.env` (`AUTH_URL`, `VALIDATE_URL`) for session creation and validation. `_local_test_server.py` mirrors the API contract for offline testing.
- Locks input for a cooldown window after repeated failed attempts.

<h3 id="contributing">Contributing</h3>

Contributions are welcome! Please feel free to submit a Pull Request.

<h3 id="license">License</h3>

This project is licensed under the MIT License - see the LICENSE file for details.

---

<a name="korean"></a>
## 한국어

자동화된 키스트로크 시퀀스를 화면 픽셀 매칭을 기반으로 실행하는 Python 데스크톱 자동화 도구입니다. Tkinter UI에서 프로필과 퀵 이벤트를 구성한 뒤, 감지한 픽셀과 일치할 때마다 미리 정의한 키 입력을 재생합니다. 현재는 macOS(PyObjC) 환경에서 주로 테스트되었으며, 동일한 코드 경로가 Windows(win32 API 환경)에서도 동작하도록 구성되어 있습니다.

### 목차
- [기능](#기능)
- [프로젝트 구조](#프로젝트-구조)
- [요구사항](#요구사항)
- [설치](#설치)
- [사용법](#사용법)
- [보안 기능](#보안-기능)
- [기여](#기여)
- [라이선스](#라이선스)

<h3 id="기능">기능</h3>

- 프로세스 리스트를 실시간으로 불러와 올바른 창에만 입력을 보냄
- MSS/NumPy를 활용한 정확한 픽셀/영역 매칭 기반 키 입력 실행
- 프로필/즐겨찾기/복제/삭제 기능과 자동 생성되는 “Quick” 프로필
- ALT/CTRL/마우스 조합으로 화면에서 바로 이벤트를 캡처하는 퀵 이벤트 편집기
- 지연·랜덤화·모디파이어·핫키·사운드 등을 세밀하게 조정하는 설정 창
- 원격 인증 서버와 연동되는 선택형 보안 모드(`main_secure.py`)

<h3 id="프로젝트-구조">프로젝트 구조</h3>

프로젝트는 각각 다른 기능을 담당하는 여러 Python 파일로 구성되어 있습니다:

- `_lambda.py`: 원격 인증을 위한 AWS Lambda 유틸리티.
- `_local_test_server.py`: 인증 API를 흉내 내는 로컬 서버.
- `main.py`: 기본 GUI 실행 진입점.
- `main_secure.py`: 인증 UI를 거친 후 메인 앱을 여는 보안 진입점.
- `keystroke_simulator_app.py`: Tkinter 기반 메인 UI, 프로세스 콤보, 각종 윈도우 및 스레드 관리.
- `keystroke_capturer.py`: 커서 주변 100×100 픽셀을 `mss`로 주기 캡처해 퀵 이벤트 미리보기 제공.
- `keystroke_event_editor.py`: 이벤트 세부 설정(시간/키/픽셀) 편집기.
- `keystroke_event_importer.py`: 다른 프로필에서 이벤트를 가져오는 도구.
- `keystroke_models.py`: 프로필·이벤트·설정 데이터 클래스.
- `keystroke_modkeys.py`: 모디파이어 패스스루/매크로 설정 창.
- `keystroke_processor.py`: 바운딩 박스 기반 정확한 픽셀/영역 매칭으로 키 입력을 발행하는 엔진.
- `keystroke_profiles.py`: Pickle 기반 프로필 로더/저장/즐겨찾기 관리.
- `keystroke_quick_event_editor.py`: ALT/CTRL 조작으로 화면에서 바로 이벤트를 캡처하는 오버레이.
- `keystroke_settings.py`: `user_settings.json` 및 base64 백업으로 설정을 저장하는 창.
- `keystroke_sort_events.py`: 프로필 이벤트 순서 정렬 UI.
- `keystroke_sounds.py`: 시작/종료 음향을 재생하는 경량 래퍼.
- `keystroke_utils.py`: 창 위치·프로세스 수집·핫키 감지·OS 추상화(PyObjC, win32).
- 부가 자원: `profiles/`(프로필 Pickle), `logs/`, `start.mp3`/`stop.mp3`, `user_settings*.b64` 등.

<h3 id="요구사항">요구사항</h3>

- Python 3.10+ (Tk/Tcl 포함). macOS Ventura/Sonoma에서 검증됨. Windows는 별도로 `pywin32` 등 win32 API 바인딩이 필요합니다.
- 가상환경 생성 후 `python -m pip install -r requirements.txt` 실행.
- 주요 외부 패키지:
    - 입력/GUI: `pynput`, `pygame`, `Pillow`, `screeninfo`.
    - 컴퓨터 비전: `mss`, `numpy`, `Cython`.
    - 공통 유틸: `loguru`, `requests`, `python-dotenv`.
    - macOS 의존성: `pyobjc` 및 각종 프레임워크 (요구사항 파일에 포함). Windows라면 해당 항목을 건너뛰고 `pywin32`를 추가 설치해야 합니다.
- `tkinter`는 CPython에 기본 포함되어 있으나, Windows에서는 Python 설치 시 Tk 옵션을 포함했는지 확인하세요.

<h3 id="설치">설치</h3>

1. 저장소 복제:
   ```
   git clone https://github.com/sh1n-k/KeystrokeSimulator.git
   ```
2. 프로젝트 디렉터리 이동:
   ```
   cd KeystrokeSimulator
   ```
3. (권장) 가상환경 생성:
   ```
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   ```
4. 의존성 설치:
   ```
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   ```
5. 보안 모드를 사용할 경우 `.env` 파일에 `AUTH_URL`, `VALIDATE_URL`을 정의하고 필요하면 `_local_test_server.py`로 API를 모의합니다.

<h3 id="사용법">사용법</h3>

1. 기본 GUI 실행:
   ```
   python main.py
   ```
   인증을 강제하려면 아래 명령을 사용합니다.
   ```
   python main_secure.py
   ```
   보안 모드는 사용자 ID를 입력받고 서버 토큰을 검증한 뒤 앱을 실행합니다.

2. "Process" 콤보박스에서 대상으로 삼을 프로세스를 선택합니다. 새 프로세스가 생겼다면 Refresh 버튼으로 갱신하세요.

3. 프로필 선택/생성:
   - 프로필은 `profiles/*.pkl`로 저장되며 "Quick" 프로필은 자동 생성됩니다.
   - Copy/Delete 버튼으로 변형본을 손쉽게 관리할 수 있고, 즐겨찾기는 상위에 노출됩니다.

4. 이벤트 구성:
   - **Quick Events**: 작은 미리보기 창이 열립니다. `ALT`로 캡처 위치를 옮기고, 마우스 클릭으로 십자선을 표시한 뒤 `CTRL`(또는 Grab 버튼)로 현재 이미지를 키와 함께 저장합니다.
   - **Edit Profile**: 각 이벤트의 시간, 반복, 참조 색상 등을 세밀하게 손봅니다.
   - **ModKeys / Sort Profile**: 모디파이어 패스스루, 실행 순서 등을 조정합니다.

5. **Settings**에서 지연, 랜덤화, 핫키를 조정하고 필요 시 사운드를 enable/disable 합니다.

6. **Start** 버튼 또는 지정한 핫키로 실행/정지합니다. 프로세서는 정확한 픽셀/영역 매칭을 통해 일치하는 구역에서만 키 입력을 전송합니다.

<h3 id="보안-기능">보안 기능</h3>

보안 버전(`main_secure.py`)은 메인 앱 앞단에 인증 절차를 추가합니다.
- 장치 ID를 생성한 뒤 `user_settings*.b64`에 암호화해 저장합니다.
- 설정/프로필 메타데이터를 암호화한 상태로 디스크에 기록합니다.
- `.env`에 정의된 `AUTH_URL`, `VALIDATE_URL`로 세션 생성/검증을 수행합니다. 오프라인 테스트는 `_local_test_server.py`로 가능합니다.
- 연속 실패 시 입력창을 일정 시간 잠그는 쿨다운 로직이 포함되어 있습니다.

<h3 id="기여">기여</h3>

기여는 환영합니다! Pull Request를 자유롭게 제출해 주세요.

<h3 id="라이선스">라이선스</h3>

이 프로젝트는 MIT 라이선스에 따라 라이선스가 부여됩니다 - 자세한 내용은 LICENSE 파일을 참조하세요.
