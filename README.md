# Keystroke Simulator

![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)
![Tkinter](https://img.shields.io/badge/Tkinter-GUI-FFCC33)
![NumPy](https://img.shields.io/badge/NumPy-013243?logo=numpy&logoColor=white)


[한국어](#korean) | [English](#english)

<a name="korean"></a>
## 한국어

화면 픽셀/영역 변화를 감지하여 미리 정의한 키 입력을 자동 실행하는 Python 데스크톱 자동화 도구입니다. Tkinter 기반이며, macOS(PyObjC)를 주 대상으로 Windows(win32)도 지원합니다.

### 기능

- **픽셀/영역 매칭** — MSS + NumPy 기반 정밀 1px 또는 5-체크포인트 영역 매칭
- **조건 체인** — 다른 이벤트의 활성/비활성 상태를 조건으로 설정 (DFS 순환 감지)
- **그룹 우선순위** — 같은 그룹 내 상호 배타적 이벤트 (낮은 priority 우선)
- **반전 매칭** — 픽셀/영역이 *불일치*할 때 트리거
- **독립 스레드** — 이벤트별 별도 스레드로 빠른 반응
- **프로필 관리** — 자동 저장, 즐겨찾기, 복사/삭제, 가져오기/내보내기
- **이벤트 그래프** — 조건 관계를 방향 그래프로 시각화
- **한국어 UI** — 이벤트 편집기 탭: 기본, 상세 설정, 조건/그룹

### 빠른 시작

```bash
git clone https://github.com/sh1n-k/KeystrokeSimulator.git
cd KeystrokeSimulator
uv python install 3.13
uv sync
uv run python main.py
```

### 실행 스크립트

```bash
run_main.cmd         # Windows
./run_main.command   # macOS
```

검증만 하려면 `--check` 옵션을 사용할 수 있습니다.

### 요구사항

- `uv` 0.7+
- Python 3.13 (Tk/Tcl 포함, `.python-version` / `requires-python`로 고정)
- macOS/Windows 의존성은 `pyproject.toml`의 환경 마커로 자동 선택
- 의존성 기준(source of truth)은 `pyproject.toml`과 `uv.lock`입니다.

### 테스트

```bash
uv run python run_tests.py
```

### 빌드

```bash
uv sync --group build
uv run python scripts/build_secure.py    # PyInstaller 단일 실행 파일

./build_secure.command   # macOS wrapper
build_secure.cmd         # Windows wrapper
```

### 라이선스

MIT — [LICENSE](LICENSE) 참조.

---

<a name="english"></a>
## English

A Python desktop automation tool that watches screen regions for pixel/color changes and replays predefined keystroke sequences. Built with Tkinter, primarily for macOS (PyObjC) with Windows (win32) support.

### Features

- **Pixel & region matching** — exact pixel or 5-checkpoint area matching via MSS + NumPy
- **Condition chains** — events can depend on other events' states (DFS cycle detection)
- **Group priority** — mutually exclusive events within a group (lowest priority wins)
- **Inverted matching** — trigger when a pixel/region does *not* match
- **Independent threads** — per-event threads for time-critical responses
- **Profile management** — auto-save, favorites, copy/delete, import/export
- **Event graph visualization** — directed graph of condition relationships
- **Korean UI** — event editor with tabs: 기본, 상세 설정, 조건/그룹

### Quick Start

```bash
git clone https://github.com/sh1n-k/KeystrokeSimulator.git
cd KeystrokeSimulator
uv python install 3.13
uv sync
uv run python main.py
```

### Launch Scripts

```bash
run_main.cmd         # Windows
./run_main.command   # macOS
```

Use `--check` to verify the environment without opening the GUI.

### Requirements

- `uv` 0.7+
- Python 3.13 (with Tk/Tcl, pinned via `.python-version` / `requires-python`)
- macOS/Windows dependencies are selected automatically via environment markers in `pyproject.toml`
- `pyproject.toml` and `uv.lock` are the source of truth for dependencies

### Testing

```bash
uv run python run_tests.py
```

### Build

```bash
uv sync --group build
uv run python scripts/build_secure.py    # PyInstaller single executable

./build_secure.command   # macOS wrapper
build_secure.cmd         # Windows wrapper
```

### License

MIT — see [LICENSE](LICENSE).
