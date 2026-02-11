# Keystroke Simulator / 키스트로크 시뮬레이터

[English](#english) | [한국어](#korean)

<a name="english"></a>
## English

A Python desktop automation tool that captures small screen regions, watches for pixel/region changes, and replays predefined keystroke sequences through a Tkinter GUI. The app focuses on macOS (PyObjC) but shares the same code paths for Windows with a matching win32 environment.

### Table of Contents
- [Features](#features)
- [Project Structure](#project-structure)
- [Requirements](#requirements)
- [Installation](#installation)
- [Usage](#usage)
- [Testing](#testing)
- [Security Features](#security-features)
- [Build & Distribution](#build--distribution)
- [Contributing](#contributing)
- [License](#license)

<h3 id="features">Features</h3>

- **Process selection** with live process enumeration so keystrokes only target the correct window.
- **Pixel & region matching** powered by MSS screen grabs and numpy — exact 1px pixel matching or 5-checkpoint area matching.
- **Inverted matching** to trigger events when a pixel/region does *not* match.
- **Condition chains** with DFS-based cycle detection — events can depend on other events' activation states.
- **Group priority** for mutually exclusive events within a group (lowest priority value wins).
- **Independent thread events** that run in separate threads for ultra-fast response.
- **Profile management** with auto-save (250ms debounce), favorites, copy/delete, and a default "Quick" profile.
- **Event dependency graph** visualization (PIL-based) showing condition relationships, groups, and badges.
- **Quick Event capture** that records reference pixels directly from the screen (ALT to reposition, CTRL to grab).
- **Korean UI** throughout the event editor (tabs: 기본, 상세 설정, 조건/그룹).
- **Fine-grained settings** for delays, modifier keys, hotkeys, and loop timing plus audible start/stop cues (base64-embedded sounds).
- **Optional secure mode** (`main_secure.py`) that authenticates devices against a remote service.

<h3 id="project-structure">Project Structure</h3>

#### Core Application

- `main.py`: Standard entry point that launches the Tkinter app.
- `main_secure.py`: Entry point that injects the authentication flow before opening the main UI.
- `keystroke_simulator_app.py`: Core Tkinter GUI — process selection, profile management, event lifecycle coordination, and state-safe start/stop toggle.
- `keystroke_processor.py`: Runtime engine — builds a mega_rect bounding box, performs pixel/region matching through a 5-stage pipeline (collect → resolve → update states → filter → execute).
- `keystroke_profiles.py`: Filesystem-backed profile manager (Pickle persistence) with auto-save, favorites, copy/delete, and integrated graph viewer.

#### Event Editors

- `keystroke_event_editor.py`: Full editor with Korean UI — 3 tabs (기본/상세 설정/조건·그룹), condition chain editor with click-to-cycle states, matching mode selection, group/priority controls.
- `keystroke_quick_event_editor.py`: Lightweight overlay for capturing events without leaving the main screen (ALT moves, CTRL grabs).

#### Models & Configuration

- `keystroke_models.py`: Dataclasses for `ProfileModel`, `EventModel`, and `UserSettings`.
- `keystroke_settings.py`: Settings dialog and JSON serialization to `user_settings.json`.
- `keystroke_modkeys.py`: Modifier key passthrough and macro configuration.

#### Utilities & Visualization

- `keystroke_utils.py`: OS abstractions for window management, process enumeration, hotkey detection (PyObjC on macOS, win32 on Windows).
- `keystroke_capturer.py`: Captures 100×100 pixel regions via `mss` for live previews.
- `keystroke_sounds.py`: Pygame-based audio cues with sounds embedded as base64 (graceful degradation when no audio hardware).
- `keystroke_event_graph.py`: Component/level-based event dependency graph — topological layout, Bezier edges, group backgrounds, badge system (independent/missing/disabled/condition).
- `keystroke_sort_events.py`: UI for reordering events inside a profile.
- `keystroke_event_importer.py`: Cross-profile event migration utility.

#### Build & Infrastructure

- `_build.py`: PyInstaller build script (`--onefile --noconsole --clean --noupx`).
- `_timestamp.py`: Version/build timestamp utilities.
- `_update_sound.py`: Sound asset update utility (base64 encoding).
- `_lambda.py`: AWS Lambda helper for device authentication.
- `_local_test_server.py`: Local test harness that mimics the authentication backend.
- `run_tests.py`: Cross-platform test runner.

#### Data & Assets

- `profiles/`: Pickle-serialized profile files (`*.pkl`).
- `logs/`: Runtime logs (loguru).
- `user_settings.json`: User settings.
- `user_settings*.b64`: Encrypted settings backups.
- `app_state.json`: Application state.
- `tests/`: Unit and integration tests.

<h3 id="requirements">Requirements</h3>

- Python 3.13 with Tk/Tcl installed (macOS Ventura/Sonoma/Sequoia tested; Windows requires the matching win32 API stack such as `pywin32`).
- Create a virtual environment and install dependencies via `python -m pip install -r requirements.txt`.
- Key third-party packages pulled in by `requirements.txt`:
    - Input/GUI stack: `pynput`, `pygame`, `Pillow`, `screeninfo`.
    - Vision + automation: `mss`, `numpy`.
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
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
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

2. Pick the target process via the "Process" combobox (use Refresh to rescan running apps).

3. Choose or create a profile:
   - Profiles live under `profiles/*.pkl`. The default "Quick" profile is auto-created.
   - Use Copy/Delete to manage variations. Favorites bubble to the top of the list.
   - Changes are auto-saved with a 250ms debounce.

4. Configure events:
   - **Quick Events**: Opens a live capture window. Use `ALT` to move the capture area, left-click to place the crosshair, press `CTRL` (or the Grab button) to save.
   - **Edit Profile**: Full editor with 3 Korean-labeled tabs — 기본 (basic), 상세 설정 (detail), 조건/그룹 (conditions/groups).
   - **Graph**: Visualize event dependencies as a directed graph with group backgrounds and status badges.
   - **ModKeys / Sort Profile**: Adjust modifier macros and order of execution.

5. Tune the delays and timing in **Settings** — start/stop key, key press duration range, loop delay range.

6. Press **Start**. The processor watches for exact pixel/region matches inside the selected process and sends keystrokes with randomized intervals. Use **Start** again (or configured hotkeys) to stop.

<h3 id="testing">Testing</h3>

Run the full test suite:
```
python run_tests.py
```

Test files in `tests/`:
- `test_condition_and_core_logic.py`: Condition filtering, group priority, evaluate_and_execute.
- `test_invert_condition_chain.py`: Inverted matching with condition chains.
- `test_check_match.py`: Pixel/region matching, inverted matching, edge cases.
- `test_event_data_conversion.py`: EventModel → event_data conversion, mega_rect calculation.

<h3 id="security-features">Security Features</h3>

The secure build (`main_secure.py`) layers an authentication gate before the simulator launches:
- Generates and stores device identifiers in `user_settings*.b64`.
- Encrypts local settings and profile metadata before persisting to disk.
- Talks to the URLs defined in `.env` (`AUTH_URL`, `VALIDATE_URL`) for session creation and validation. `_local_test_server.py` mirrors the API contract for offline testing.
- Locks input for a cooldown window after repeated failed attempts.

<h3 id="build--distribution">Build & Distribution</h3>

Build a single executable with PyInstaller:
```
python _build.py
```
- Output: `main_secure_v3.0` (single executable, `--onefile --noconsole --clean --noupx`).
- Embeds `.env` variables (`AUTH_URL`, `VALIDATE_URL`) into the build.

<h3 id="contributing">Contributing</h3>

Contributions are welcome! Please feel free to submit a Pull Request.

<h3 id="license">License</h3>

This project is licensed under the MIT License - see the LICENSE file for details.

---

<a name="korean"></a>
## 한국어

화면 픽셀/영역 매칭을 기반으로 자동화된 키스트로크 시퀀스를 실행하는 Python 데스크톱 자동화 도구입니다. Tkinter UI에서 프로필과 이벤트를 구성한 뒤, 감지한 픽셀과 일치(또는 불일치)할 때마다 미리 정의한 키 입력을 재생합니다. macOS(PyObjC) 환경에서 주로 테스트되었으며, Windows(win32 API)에서도 동작합니다.

### 목차
- [기능](#기능)
- [프로젝트 구조](#프로젝트-구조)
- [요구사항](#요구사항)
- [설치](#설치)
- [사용법](#사용법)
- [테스트](#테스트)
- [보안 기능](#보안-기능)
- [빌드 및 배포](#빌드-및-배포)
- [기여](#기여)
- [라이선스](#라이선스)

<h3 id="기능">기능</h3>

- **프로세스 선택** — 실시간 프로세스 목록에서 타겟 창을 지정하여 올바른 윈도우에만 입력 전송.
- **픽셀/영역 매칭** — MSS/NumPy 기반 정확한 1px 픽셀 매칭 또는 5-체크포인트 영역 매칭.
- **반전 매칭** — 지정한 픽셀/영역이 *일치하지 않을 때* 트리거하는 옵션.
- **조건 체인** — DFS 기반 순환 의존 감지, 다른 이벤트의 활성/비활성 상태를 조건으로 설정.
- **그룹 우선순위** — 같은 그룹 내 이벤트는 상호 배타적으로 동작 (낮은 priority 값이 우선).
- **독립 스레드 이벤트** — 별도 스레드에서 초고속 반응.
- **프로필 관리** — 자동 저장(250ms debounce), 즐겨찾기, 복사/삭제, 기본 "Quick" 프로필 자동 생성.
- **이벤트 의존성 그래프** — PIL 기반 시각화 (조건 관계, 그룹 배경, 상태 뱃지).
- **퀵 이벤트 캡처** — ALT/CTRL/마우스 조합으로 화면에서 직접 이벤트 캡처.
- **한국어 UI** — 이벤트 편집기 전체 한국어화 (탭: 기본, 상세 설정, 조건/그룹).
- **세밀한 설정** — 지연, 랜덤화, 모디파이어, 핫키, 사운드 (base64 임베딩).
- **선택형 보안 모드** — `main_secure.py`로 원격 인증 서버 연동.

<h3 id="프로젝트-구조">프로젝트 구조</h3>

#### 핵심 애플리케이션

- `main.py`: 기본 GUI 실행 진입점.
- `main_secure.py`: 인증 UI를 거친 후 메인 앱을 여는 보안 진입점.
- `keystroke_simulator_app.py`: Tkinter 기반 메인 UI — 프로세스 선택, 프로필 관리, 이벤트 생명주기 조정, 상태 안전한 시작/중지 토글.
- `keystroke_processor.py`: 런타임 엔진 — mega_rect 바운딩 박스 기반 픽셀/영역 매칭, 5단계 파이프라인 (수집 → 해석 → 상태 갱신 → 필터 → 실행).
- `keystroke_profiles.py`: Pickle 기반 프로필 관리 — 자동 저장, 즐겨찾기, 복사/삭제, 그래프 뷰어 통합.

#### 이벤트 편집기

- `keystroke_event_editor.py`: 한국어 UI 이벤트 편집기 — 3개 탭 (기본/상세 설정/조건·그룹), 클릭 순환 조건 편집기, 매칭 모드 선택, 그룹/우선순위 제어.
- `keystroke_quick_event_editor.py`: ALT/CTRL 조작으로 화면에서 바로 이벤트를 캡처하는 오버레이.

#### 모델 및 설정

- `keystroke_models.py`: `ProfileModel`, `EventModel`, `UserSettings` 데이터 클래스.
- `keystroke_settings.py`: 설정 다이얼로그 및 `user_settings.json` JSON 직렬화.
- `keystroke_modkeys.py`: 모디파이어 키 패스스루/매크로 설정.

#### 유틸리티 및 시각화

- `keystroke_utils.py`: OS 추상화 — 창 관리, 프로세스 수집, 핫키 감지 (PyObjC/win32).
- `keystroke_capturer.py`: `mss`로 100×100 픽셀 영역 캡처 (라이브 미리보기).
- `keystroke_sounds.py`: Pygame 기반 사운드 — base64 임베딩 (오디오 하드웨어 없을 시 정상 대응).
- `keystroke_event_graph.py`: 컴포넌트/레벨 기반 이벤트 의존성 그래프 — 위상 정렬 레이아웃, 베지어 곡선, 그룹 배경, 뱃지 시스템.
- `keystroke_sort_events.py`: 프로필 이벤트 순서 정렬 UI.
- `keystroke_event_importer.py`: 프로필 간 이벤트 마이그레이션 도구.

#### 빌드 및 인프라

- `_build.py`: PyInstaller 빌드 스크립트 (`--onefile --noconsole --clean --noupx`).
- `_timestamp.py`: 버전/빌드 타임스탬프 유틸리티.
- `_update_sound.py`: 사운드 에셋 업데이트 유틸리티 (base64 인코딩).
- `_lambda.py`: AWS Lambda 인증 헬퍼.
- `_local_test_server.py`: 인증 API 모의 로컬 서버.
- `run_tests.py`: 크로스 플랫폼 테스트 러너.

#### 데이터 및 에셋

- `profiles/`: Pickle 직렬화 프로필 파일 (`*.pkl`).
- `logs/`: 런타임 로그 (loguru).
- `user_settings.json`: 사용자 설정.
- `user_settings*.b64`: 암호화된 설정 백업.
- `app_state.json`: 애플리케이션 상태.
- `tests/`: 단위 및 통합 테스트.

<h3 id="요구사항">요구사항</h3>

- Python 3.13 (Tk/Tcl 포함). macOS Ventura/Sonoma/Sequoia에서 검증됨. Windows는 별도로 `pywin32` 등 win32 API 바인딩이 필요합니다.
- 가상환경 생성 후 `python -m pip install -r requirements.txt` 실행.
- 주요 외부 패키지:
    - 입력/GUI: `pynput`, `pygame`, `Pillow`, `screeninfo`.
    - 컴퓨터 비전: `mss`, `numpy`.
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

2. "Process" 콤보박스에서 대상 프로세스를 선택합니다. 새 프로세스가 생겼다면 Refresh 버튼으로 갱신하세요.

3. 프로필 선택/생성:
   - 프로필은 `profiles/*.pkl`로 저장되며 "Quick" 프로필은 자동 생성됩니다.
   - Copy/Delete 버튼으로 변형본을 관리할 수 있고, 즐겨찾기는 상위에 노출됩니다.
   - 변경사항은 250ms 디바운스 후 자동 저장됩니다.

4. 이벤트 구성:
   - **Quick Events**: 작은 미리보기 창이 열립니다. `ALT`로 위치 이동, 마우스 클릭으로 십자선 표시, `CTRL`로 캡처 저장.
   - **Edit Profile**: 한국어 UI 편집기 — 기본(좌표/키), 상세 설정(매칭 모드/타이밍), 조건/그룹(의존성/우선순위).
   - **Graph**: 이벤트 의존성을 방향 그래프로 시각화 (그룹 배경, 상태 뱃지 포함).
   - **ModKeys / Sort Profile**: 모디파이어 패스스루, 실행 순서 등을 조정합니다.

5. **Settings**에서 시작/중지 키, 키 누름 시간 범위, 루프 간 지연 범위를 조정합니다.

6. **Start** 버튼 또는 지정한 핫키로 실행/정지합니다. 프로세서는 정확한 픽셀/영역 매칭을 통해 일치하는 구역에서만 키 입력을 전송합니다.

<h3 id="테스트">테스트</h3>

전체 테스트 실행:
```
python run_tests.py
```

`tests/` 내 테스트 파일:
- `test_condition_and_core_logic.py`: 조건 필터링, 그룹 우선순위, evaluate_and_execute.
- `test_invert_condition_chain.py`: 반전 매칭과 조건 체인.
- `test_check_match.py`: 픽셀/영역 매칭, 반전 매칭, 엣지 케이스.
- `test_event_data_conversion.py`: EventModel → event_data 변환, mega_rect 계산.

<h3 id="보안-기능">보안 기능</h3>

보안 버전(`main_secure.py`)은 메인 앱 앞단에 인증 절차를 추가합니다.
- 장치 ID를 생성한 뒤 `user_settings*.b64`에 암호화해 저장합니다.
- 설정/프로필 메타데이터를 암호화한 상태로 디스크에 기록합니다.
- `.env`에 정의된 `AUTH_URL`, `VALIDATE_URL`로 세션 생성/검증을 수행합니다. 오프라인 테스트는 `_local_test_server.py`로 가능합니다.
- 연속 실패 시 입력창을 일정 시간 잠그는 쿨다운 로직이 포함되어 있습니다.

<h3 id="빌드-및-배포">빌드 및 배포</h3>

PyInstaller로 단일 실행 파일 빌드:
```
python _build.py
```
- 출력: `main_secure_v3.0` (단일 실행 파일, `--onefile --noconsole --clean --noupx`).
- `.env` 변수(`AUTH_URL`, `VALIDATE_URL`)를 빌드에 포함합니다.

<h3 id="기여">기여</h3>

기여는 환영합니다! Pull Request를 자유롭게 제출해 주세요.

<h3 id="라이선스">라이선스</h3>

이 프로젝트는 MIT 라이선스에 따라 라이선스가 부여됩니다 - 자세한 내용은 LICENSE 파일을 참조하세요.
