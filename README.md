# Keystroke Simulator / 키스트로크 시뮬레이터

[English](#english) | [한국어](#korean)

<a name="english"></a>
## English

A Python application to create, manage, and execute automated keystroke sequences.

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

- Process selection for targeting specific applications
- Profile management for organizing keystroke sequences
- Quick Events for rapid setup of keystroke patterns
- Customizable settings for key press durations and delays
- Sound notifications for start and stop actions
- Secure device authentication system

<h3 id="project-structure">Project Structure</h3>

The project consists of several Python files, each responsible for different functionalities:

- `_lambda.py`: AWS Lambda function for server-side device authentication.
- `_local_test_server.py`: A local test server to simulate the authentication backend.
- `main.py`: Entry point for the application.
- `main_secure.py`: Secure version with device authentication.
- `keystroke_simulator_app.py`: Main application GUI and logic.
- `keystroke_capturer.py`: Module to capture keystroke sequences from the user.
- `keystroke_event_editor.py`: GUI for editing individual keystroke events.
- `keystroke_event_importer.py`: Functionality for importing events from other profiles.
- `keystroke_models.py`: Data models for the application.
- `keystroke_modkeys.py`: Manages modifier keys (e.g., Shift, Ctrl, Alt).
- `keystroke_processor.py`: Process management and collection.
- `keystroke_profiles.py`: Profile management system.
- `keystroke_quick_event_editor.py`: Quick event creation and editing.
- `keystroke_settings.py`: Application settings management.
- `keystroke_sort_events.py`: Event sorting functionality.
- `keystroke_utils.py`: Utility functions and classes.

<h3 id="requirements">Requirements</h3>

- Python 3.x
- Required Python packages (install via `pip install -r requirements.txt`):
    - tkinter
    - pygame
    - pynput
    - Pillow
    - loguru
    - requests
    - python-dotenv
    - cryptography

<h3 id="installation">Installation</h3>

1. Clone the repository:
   ```
   git clone https://github.com/yourusername/keystroke-simulator.git
   ```
2. Navigate to the project directory:
   ```
   cd keystroke-simulator
   ```
3. Install the required packages:
   ```
   pip install -r requirements.txt
   ```

<h3 id="usage">Usage</h3>

1. Run the main application:
   ```
   python main.py
   ```
   Or for the secure version with device authentication:
   ```
   python main_secure.py
   ```

2. Select a target process from the dropdown menu.
3. Choose or create a profile for your keystroke sequences.
4. Use the "Quick Events" or "Edit Profile" buttons to set up your keystroke patterns.
5. Click "Start" to begin the keystroke simulation.

<h3 id="security-features">Security Features</h3>

The secure version (`main_secure.py`) includes:
- Device ID generation and storage
- Encrypted local storage of device information
- Server-side authentication

<h3 id="contributing">Contributing</h3>

Contributions are welcome! Please feel free to submit a Pull Request.

<h3 id="license">License</h3>

This project is licensed under the MIT License - see the LICENSE file for details.

---

<a name="korean"></a>
## 한국어

자동화된 키스트로크 시퀀스를 생성, 관리 및 실행하는 Python 애플리케이션입니다.

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

- 특정 애플리케이션을 대상으로 하는 프로세스 선택
- 키스트로크 시퀀스를 구성하기 위한 프로필 관리
- 키스트로크 패턴의 빠른 설정을 위한 퀵 이벤트
- 키 누름 지속 시간 및 지연에 대한 사용자 정의 설정
- 시작 및 중지 작업에 대한 사운드 알림
- 보안 장치 인증 시스템

<h3 id="프로젝트-구조">프로젝트 구조</h3>

프로젝트는 각각 다른 기능을 담당하는 여러 Python 파일로 구성되어 있습니다:

- `_lambda.py`: 서버 측 장치 인증을 위한 AWS Lambda 함수.
- `_local_test_server.py`: 인증 백엔드를 시뮬레이션하기 위한 로컬 테스트 서버.
- `main.py`: 애플리케이션의 진입점.
- `main_secure.py`: 장치 인증이 포함된 보안 버전.
- `keystroke_simulator_app.py`: 메인 애플리케이션 GUI 및 로직.
- `keystroke_capturer.py`: 사용자로부터 키스트로크 시퀀스를 캡처하는 모듈.
- `keystroke_event_editor.py`: 개별 키스트로크 이벤트 편집을 위한 GUI.
- `keystroke_event_importer.py`: 다른 프로필에서 이벤트를 가져오는 기능.
- `keystroke_models.py`: 애플리케이션의 데이터 모델.
- `keystroke_modkeys.py`: 보조 키(예: Shift, Ctrl, Alt)를 관리.
- `keystroke_processor.py`: 프로세스 관리 및 수집.
- `keystroke_profiles.py`: 프로필 관리 시스템.
- `keystroke_quick_event_editor.py`: 퀵 이벤트 생성 및 편집.
- `keystroke_settings.py`: 애플리케이션 설정 관리.
- `keystroke_sort_events.py`: 이벤트 정렬 기능.
- `keystroke_utils.py`: 유틸리티 함수 및 클래스.

<h3 id="요구사항">요구사항</h3>

- Python 3.x
- 필요한 Python 패키지 (`pip install -r requirements.txt`로 설치):
    - tkinter
    - pygame
    - pynput
    - Pillow
    - loguru
    - requests
    - python-dotenv
    - cryptography

<h3 id="설치">설치</h3>

1. 저장소 복제:
   ```
   git clone https://github.com/yourusername/keystroke-simulator.git
   ```
2. 프로젝트 디렉토리로 이동:
   ```
   cd keystroke-simulator
   ```
3. 필요한 패키지 설치:
   ```
   pip install -r requirements.txt
   ```

<h3 id="사용법">사용법</h3>

1. 메인 애플리케이션 실행:
   ```
   python main.py
   ```
   또는 장치 인증이 포함된 보안 버전:
   ```
   python main_secure.py
   ```

2. 드롭다운 메뉴에서 대상 프로세스를 선택합니다.
3. 키스트로크 시퀀스에 대한 프로필을 선택하거나 생성합니다.
4. "퀵 이벤트" 또는 "프로필 편집" 버튼을 사용하여 키스트로크 패턴을 설정합니다.
5. "시작"을 클릭하여 키스트로크 시뮬레이션을 시작합니다.

<h3 id="보안-기능">보안 기능</h3>

보안 버전(`main_secure.py`)에는 다음이 포함됩니다:
- 장치 ID 생성 및 저장
- 장치 정보의 암호화된 로컬 저장
- 서버 측 인증

<h3 id="기여">기여</h3>

기여는 환영합니다! Pull Request를 자유롭게 제출해 주세요.

<h3 id="라이선스">라이선스</h3>

이 프로젝트는 MIT 라이선스에 따라 라이선스가 부여됩니다 - 자세한 내용은 LICENSE 파일을 참조하세요.
