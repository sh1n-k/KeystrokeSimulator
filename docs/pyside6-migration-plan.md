# Tkinter → PySide6 전환 계획

- 권장 추론 레벨: xhigh (장기·다단계 작업)
- 작업 위치: `git worktree add ../KeystrokeSimulator-qt -b feat/pyside6` (대규모 변경이라 main 직접 작업 금지)
- 성공 기준: 각 단계 `uv run -m scripts.verify` 통과 + diff 리뷰, 최종 단계는 macOS·Windows 실기에서 아래 "기능 동등성 체크리스트" 전 항목 통과

## 0. 전제와 원칙

- 실행: `uv` + 표준 CPython 3.14 (GIL 빌드). free-threaded 3.14t는 PySide6 wheel이 없어 쓰지 않는다.
- 의존성: `PySide6-Essentials` 6.12.x (cp310-abi3 wheel, macOS universal2·Windows x64). Addons는 쓰지 않는다.
- 대상 OS: macOS(주) + Windows. 배포하지 않으므로 패키징·서명은 범위 밖이다.
- 최우선 원칙은 **핵심 기능 보존**이다. `processor.py`의 조건·그룹·runtime toggle 의미론과 `profiles/*.json`, `app_state.json` 저장 계약은 바꾸지 않는다.
- UI와 로직을 분리한다. 위젯 코드에는 표시와 입력 전달만 남기고, 상태·검증·저장·스레드 관리는 UI 독립 계층으로 옮긴다. 이 경계는 import 규칙 테스트로 강제한다.
- Tk와 Qt를 한 프로세스에서 동시에 돌리지 않는다. 전환 기간에는 **진입점 두 개**(`-m app` = Tk, `-m app.qt` = Qt)를 둔다. 같은 로직 계층을 공유하고, 마지막에 Tk를 제거한다.

## 1. 현재 상태 요약 (실측)

| 영역 | 내용 |
|---|---|
| 규모 | `app/ui` 17파일·9,947 LOC, core 2,960, storage 1,230, utils 1,504 / tests 592개 |
| Tk 결합 (ui 밖) | `app/core/capturer.py:2,119` (TclError), `app/utils/window_state.py` (Tk isinstance·grab), `app/__main__.py` (mainloop) 3곳뿐 |
| 스레드→UI | `InputListenerSession.post()` 하나(queue + socketpair + `root.after` 10ms 펌프), 그 외 `capture_hud`의 50/100ms `after` 폴링 |
| ui 의존 계층 | L0 theme·capture_session·input_listener_session·mac_hotkey_tap·mac_key_poll → L1 dialogs·event_graph·workspace_list·workspace_sidebar·main_frames·settings·modkeys·profile_settings → L2 capture_hud → L3 workspace_detail → L4 workspace → L5 simulator_app |
| ui 안의 순수 로직 | workspace_list(배지·요약), workspace_detail(issues·clamp), capture_hud(좌표 변환·렌더·hud_position), event_graph(그래프 알고리즘 전체), capture_session 전체 |
| 위젯에 섞인 로직 | workspace(undo 스택·자동 저장), simulator_app(`toggle_start_stop` 상태 전이·readiness), settings(`on_ok` 검증), capture_hud(`_check_keys` 키 상태기·CTRL/ALT 처리) |
| 입력 리스너 | macOS: CGEventTap(키), **pynput mouse Listener(휠·버튼 트리거, macOS 포함)**, 폴백 키 폴링 / Windows: pynput 키·마우스, `GetAsyncKeyState` |
| 테스트 | Tk root 생성 4클래스(그중 `test_clear_local_logs.TestAskConfirmDialog`는 게이트 없음), `tk.Tcl()` stub 5개, `__new__` stub로 앱 흐름 테스트(64개) |
| CI | `verify.yml:29`가 없는 `tests.test_quick_event_editor`를 참조 (macOS GUI 단계 실패 추정) |
| 브랜치 | 로컬 `main`이 `origin/main`보다 11커밋 뒤 (Windows mss 적응형 캡처, 오디오 수정 등) |

## 2. 목표 구조

패키지명 `app`은 유지한다(`uv run -m app`, 문서 경로 보존). 하위 구조만 재편한다.

```
app/
  __main__.py            # Qt 부트스트랩 (전환 중에는 Tk, app/qt/__main__.py가 Qt)
  domain/                # 순수 로직. OS·UI import 금지
    models.py, validation.py, profile_events.py, run_composition.py,
    runtime_toggle.py, event_graph_layout.py, capture_geometry.py, badges.py ...
  engine/                # 실행 엔진. OS 의존, UI import 금지
    processor.py, screen_backend.py, capturer.py, key_output.py
  platform/              # OS 서비스. UI import 금지
    mac/ hotkey_tap.py, key_poll.py, mouse_tap.py(필요 시), permissions.py, app_nap.py
    win/ keys.py, process.py
    input_router.py      # 리스너 수명 + Dispatcher로 메인 스레드 전달 (현 InputListenerSession 일반화)
  storage/               # 현행 + window_state의 StateUtils(app_state.json)
  presenters/            # UI 독립 상태 모델. Qt·Tk import 금지, 콜백/옵저버로 통지
    run_controller.py    # 시작/중지 상태기, readiness, runtime toggle 반영
    workspace_model.py   # 프로필 편집, undo 스택, 자동 저장 디바운스(타이머는 주입)
    capture_controller.py# HUD 모드(single/continuous), ALT 이동·CTRL 고정 상태기, quick 이벤트
    settings_form.py     # 설정 값 검증·저장
  i18n.py, sounds.py, ...# utils 정리
  ui/                    # Qt 위젯만. 여기서만 PySide6 import
    app.py               # QApplication, 스타일·다크모드, 종료 처리
    dispatcher.py        # QObject + Signal(object) + QueuedConnection 브리지
    theme.py             # 색·간격 토큰 → QPalette/QSS
    main_window.py, workspace/ (window, sidebar, event_tree, detail, graph_view, run_set_editor),
    capture_hud.py, capture_border.py, settings_dialog.py, modkeys_dialog.py, dialogs.py
    mac_window.py        # winId()→NSWindow level·collectionBehavior (PyObjC)
```

경계 규칙 (`tests/test_import_conventions.py` 확장으로 강제):
- `PySide6`는 `app/ui/**`에서만 import한다. `tkinter`는 전환 완료 후 0건이어야 한다.
- `domain`은 `engine`·`platform`·`storage`·`ui`를 import하지 않는다.
- `presenters`는 `ui`를 import하지 않는다. 시간·타이머·스레드 전달은 `Dispatcher`/`Scheduler` 프로토콜로 주입받는다.

## 3. 단계

### P0. 준비

1. `git pull --ff-only`로 main을 origin과 맞추고, 미추적 `scripts/mac_*.py` 두 파일의 처리(커밋/보관/삭제)를 결정한다.
2. 워크트리와 브랜치 `feat/pyside6`를 만든다.
3. `verify.yml:29`의 죽은 테스트 참조를 별도 커밋으로 고친다(main에 먼저 반영해도 됨).
4. 기준선: `uv run -m scripts.verify` 통과 결과, 현재 Tk 화면 스크린샷(실행 창·작업 공간·HUD·설정·수정키), `tests/E2E_TESTPLAN.md` 체크 결과를 남긴다.

### 검증
- `uv run -m scripts.verify` 통과, `git status -sb`가 origin과 동기화.

### P1. 기술 스파이크 (go/no-go)

전환을 막을 수 있는 위험을 먼저 확인한다. 각 스파이크는 `spikes/`에 버리는 코드로 만든다.

| # | 확인 항목 | 통과 기준 | 실패 시 대안 |
|---|---|---|---|
| S1 | PySide6 6.12 + Python 3.14 설치 (macOS arm64, Windows x64) | `uv add PySide6-Essentials` 후 창 표시 | 6.11.x 고정 |
| S2 | Qt 메인 루프 + SCStream 백엔드 + CGEventTap 스레드 공존 | 10분 실행 중 크래시·프레임 정지 없음, 단축키 소비 동작 | PyObjC 쪽 NSApp 접근 정리 |
| S3 | **macOS pynput mouse Listener + Qt** (pynput #424/#510 크래시 보고) | 휠·버튼 트리거 10분 반복 OK | CGEventTap에 마우스 이벤트 마스크 추가(`platform/mac/mouse_tap.py`) |
| S4 | 워커 스레드(threading.Thread)에서 `Signal.emit` → 슬롯이 메인 스레드에서 실행 | 슬롯 안 `threading.get_ident()`가 메인 | QObject 브리지 + `@Slot` 메서드 + QueuedConnection 명시 |
| S5 | HUD 오버레이: 항상 위, 포커스 뺏지 않음, 전체화면 게임/다른 Space 위 표시 | macOS: `winId()`→NSWindow `collectionBehavior`(canJoinAllSpaces·fullScreenAuxiliary) + level 설정 후 표시 / Windows: topmost·no-activate | NSPanel 수준 조정, 또는 HUD 표시 조건 문서화 |
| S6 | 캡처 테두리 창 4개가 SCStream/mss 캡처본에 안 찍힘 | 테두리 위치의 픽셀이 캡처본과 화면이 일치 | 현행처럼 박스 밖에 배치(정책 3) |
| S7 | App Nap: Qt 백그라운드에서 dispatcher·타이머 지연 | 게임 포커스 중 단축키 반응 지연 < 50ms | 실행 중 `NSProcessInfo.beginActivity` (현 `ResponsivenessActivity` 재사용) |
| S8 | `QT_QPA_PLATFORM=offscreen` GUI 테스트가 GitHub Actions macOS·Windows에서 동작 | 샘플 위젯 테스트 통과 | GUI 테스트를 로컬 전용 게이트로 유지 |

### 검증
- 스파이크별 결과를 이 문서 부록에 기록하고, S2·S3·S5 중 대안까지 실패한 항목이 있으면 진행 여부를 다시 결정한다.

### P2. 로직 분리 (Tk 유지, 동작 불변 리팩터)

Tk 앱이 계속 돌아가는 상태에서 로직을 빼낸다. 위험이 가장 큰 단계를 Tk 회귀 테스트로 보호하면서 처리하는 것이 핵심이다. 커밋 단위는 "이동만" → "추출" 순으로 작게 나눈다.

1. **패키지 재배치 (이동만)**: core·utils를 `domain/engine/platform/storage`로 옮기고 import를 갱신한다. 로직 변경 없음. `test_import_conventions`에 경계 규칙을 추가한다.
2. **Tk 누수 제거**: `capturer.py`의 `tk.TclError` 처리를 콜백 예외 일반 처리로 바꾼다. `window_state.py`는 `StateUtils` → `storage/app_state.py`, Tk 전용 함수 → `ui` 쪽으로 나눈다.
3. **순수 함수 이동**: workspace_list 배지·요약, workspace_detail `event_issues`·`apply_capture`·`clamp_region`, capture_hud 좌표 변환·`render_overlay`·`render_magnifier`·`hud_position`·`border_rects`, event_graph 레이아웃 알고리즘과 PIL 렌더, main_frames `run_set_display`를 `domain`으로 옮긴다. 테스트도 함께 옮긴다.
4. **Dispatcher 추상화**: `InputListenerSession`을 `platform/input_router.py`로 옮기고 `TkScheduler` 대신 `Dispatcher.post(fn)` 프로토콜에 의존하게 한다. Tk 구현(socketpair + after)은 `ui` 쪽 어댑터로 남긴다.
5. **presenter 추출**:
   - `RunController`: `toggle_start_stop`, `ReadinessSnapshot`, processor 시작·중지, runtime toggle 반영, HUD 닫기 규칙(정책 4).
   - `WorkspaceModel`: 프로필·실행 세트 CRUD, undo 스택(정책 6 대상 전부), 자동 저장 디바운스, Quick 프로필 보호(정책 4), 불완전 이벤트 저장(정책 7).
   - `CaptureController`: single/continuous 모드, ALT 이동은 CTRL 고정 전까지 미적용(정책 2), CTRL 무시 조건, quick 이벤트 추가, HUD 위치 저장.
   - `SettingsForm`: `on_ok`의 검증과 저장, 언어 변경 통지.
   - Tk 위젯은 이 presenter를 호출하도록 바꾸고 동작은 그대로 둔다.
6. presenter 단위 테스트를 추가한다. 기존 `__new__` stub 기반 앱 흐름 테스트 64개는 가능한 한 presenter 테스트로 옮긴다. 이 테스트들이 Qt 전환 후 회귀를 막는 안전망이다.

### 검증
- 각 커밋마다 `uv run -m scripts.verify` (ruff, pyright strict, unittest).
- 단계 끝에 macOS·Windows 실기에서 E2E_TESTPLAN 전체 1회. Tk 앱 동작이 기준선과 같아야 한다.

### P3. Qt 기반 골격

1. `PySide6-Essentials` 의존성을 추가하고 `uv lock`을 갱신한다.
2. `app/qt/__main__.py` 진입점: QApplication, 스타일(macOS는 기본 `macOS`, Windows는 `windows11` 또는 `fusion`), `styleHints().colorScheme` 다크/라이트 대응, SIGINT 처리, 예외 훅 연결.
3. `ui/dispatcher.py`: 메인 스레드에서 만든 QObject, `Signal(object)`, `QueuedConnection`, `@Slot`. S4 결과대로 구현한다.
4. `ui/theme.py`: 기존 색·간격 토큰 상수를 유지하고 QPalette·QSS로 매핑한다. 폰트는 시스템 기본(SF Pro / Segoe UI).
5. i18n: 각 창에 `retranslate()`를 두고 언어 변경 시 열린 창 모두 호출한다. 현재는 메인 창만 재번역되는데, Qt에서는 전체로 확장한다(동작 개선이지만 비용이 작음).
6. 테스트 하네스: `unittest` 유지, `tests/qt_support.py`에 offscreen QApplication 싱글턴과 `RUN_GUI_TESTS` 게이트를 둔다.

### 검증
- `uv run -m scripts.verify` + `uv run -m app.qt`로 빈 메인 창이 뜨고 종료되는지 macOS·Windows에서 확인.

### P4. 화면 전환 (잎 → 뿌리)

각 화면은 presenter를 그대로 쓰고 위젯만 새로 만든다. 화면마다 Qt 위젯 테스트(offscreen)를 추가한다.

| 순서 | 화면 | Qt 구성 | 유의점 |
|---|---|---|---|
| 1 | 확인 대화상자 | `QMessageBox` 또는 작은 `QDialog` | 모달·Esc 닫기 |
| 2 | 설정 | `QDialog` + `QFormLayout`, 사운드 미리듣기 | 단일 SoundPlayer 공유(miniaudio 이중 디바이스 크래시) 유지, topmost 아님(정책 1) |
| 3 | 수정키 세트 | `QDialog` + 목록·편집 | 프로필과 독립 선택(정책 5) |
| 4 | 실행 창 | `QMainWindow`: 대상 프로세스·실행 대상·수정키 세트 콤보, 시작/중지, 상태 배지, 툴 메뉴 | Esc로 닫지 않음(정책 8), 창 닫기만 종료 |
| 5 | 작업 공간 | `QSplitter`: 사이드바(QListView), 이벤트 트리(`QTreeView` + `QAbstractItemModel`, 드래그 순서), 상세 패널(QFormLayout + 캡처 미리보기), 그래프 탭(PIL 이미지 → QPixmap), 실행 세트 편집기 | 자동 저장·되돌리기(⌘Z/Ctrl+Z, 정책 6), 배지(정책 7), 위쪽만 실행 그룹 드래그 |
| 6 | 캡처 HUD + 테두리 | HUD: `Qt.Tool`·`WindowStaysOnTopHint`·`WA_ShowWithoutActivating`·`WA_MacAlwaysShowToolWindow` + `mac_window.py` / 테두리: 프레임 없는 창 4개, `WA_TransparentForMouseEvents` / 확대경·미리보기: 커스텀 `QWidget.paintEvent` | ALT 추적·CTRL 고정은 CaptureController, 키 상태 폴링 100ms는 `QTimer`, 캡처 프레임 50ms 폴링 유지 또는 dispatcher 통지, 정책 1~4 |

### 검증
- 화면마다 `uv run -m scripts.verify` + 해당 Qt 위젯 테스트, 그리고 `uv run -m app.qt`로 E2E_TESTPLAN 해당 절을 macOS에서 확인한다.
- 작업 공간과 HUD 완료 후에는 Windows 실기에서도 확인한다.

### P5. 전환 완료와 정리

1. `app/__main__.py`를 Qt로 바꾸고 `app/qt/` 진입점을 합친다.
2. Tk 위젯·Tk 어댑터·Tk 테스트를 삭제하고 `tkinter` import 0건을 import 규칙 테스트로 확인한다.
3. 문서 갱신: `AGENTS.md`("Tkinter 위젯 변경은 메인 스레드" → Qt 규칙, 모듈 경계), `docs/maintainer-reference.md`(모듈 경계 표, UI 정책은 유지, Tk 세그폴트 경고 제거), `tests/E2E_TESTPLAN.md`(Qt 기준 문구), README 실행 방법.
4. CI: GUI 테스트를 offscreen으로 macOS·Windows 모두에서 실행(S8 결과에 따름).

### 검증
- `uv run -m scripts.verify`, `uv run pre-commit run --all-files`, CI 통과.

### P6. 실기 동등성 검증

macOS와 Windows에서 아래 체크리스트를 모두 통과해야 `feat/pyside6`를 main에 머지한다. 같은 프로필 JSON으로 Tk 기준선(P0)과 결과를 비교한다.

## 4. 기능 동등성 체크리스트

- [ ] 기존 `profiles/*.json`, 수정키 세트, 실행 세트, `app_state.json`을 그대로 읽고, 저장 결과가 Tk 버전과 같은 스키마다.
- [ ] 같은 프로필로 같은 화면에서 신호·규칙 매칭 결과가 같다(엔진은 변경 없음).
- [ ] 시작/중지: 버튼, 전역 단축키(키·휠·마우스 버튼), runtime toggle, Windows Alt+Shift.
- [ ] macOS 단축키 소비(CGEventTap)와 Accessibility 없을 때 폴링 폴백.
- [ ] 대상 프로세스 활성일 때만 실행, 실행 중 UI 응답, 실행 중 편집은 다음 시작부터 반영 안내.
- [ ] 작업 공간: 편집·복사·삭제·순서 드래그·그룹·조건, 자동 저장, 되돌리기 대상 전부(정책 6), 불완전 이벤트 배지, 그래프 탭, 중복 이름 거부·순환 비활성.
- [ ] Quick 프로필 삭제·이름 변경 불가, 빠른 이벤트 자동 번호 추가, 실행 시작 시 HUD 닫힘.
- [ ] 캡처 HUD: 항상 위, ALT 이동은 CTRL 고정 전 미적용, 캡처 박스 회피, 테두리가 캡처본에 안 찍힘, 이름 입력 중 CTRL 무시, 확대경 클릭, 미리보기 고정.
- [ ] 설정: 언어 전환(열린 창 모두), key pressed time·루프 딜레이, 알림음, 초기화는 확인 전 미저장.
- [ ] 창 위치 복원(화면 밖 방지), 메인 창 Esc로 닫지 않음, 보조 창 Esc로 닫힘.
- [ ] 화면 기록·Accessibility 권한 안내.
- [ ] macOS 다크/라이트 모드, Windows 11 표시.

## 5. 위험과 대응

| 위험 | 영향 | 대응 |
|---|---|---|
| macOS에서 pynput + Qt 크래시 | 휠·마우스 트리거 불능 | S3에서 확인, 실패 시 CGEventTap 마우스 탭으로 교체(키 탭과 같은 구조) |
| HUD가 전체화면 게임 위에 안 뜸 | 캡처 작업 불편 | S5에서 NSWindow 설정 검증, 안 되면 창 모드 게임 기준으로 사용 문서화 |
| PySide6 6.8+ 함수 슬롯 스레드 동작 | UI 갱신이 워커 스레드에서 실행 | dispatcher는 QObject 메서드 슬롯 + QueuedConnection 고정, 테스트로 스레드 ID 검증 |
| P2 리팩터 중 회귀 | 핵심 기능 손상 | 이동과 로직 변경 커밋 분리, 커밋마다 verify, 단계 끝 실기 E2E |
| offscreen CI 불안정 | CI 신뢰도 저하 | GUI 테스트는 게이트 유지, presenter 테스트에 로직 검증 집중 |
| Windows 실기 검증 공백 | Windows 회귀 | P2·P4·P6 끝마다 Windows 실기 체크 필수 |
| 작업 기간 중 main 변경 | 머지 충돌 | 주기적으로 main을 브랜치에 병합, P2 이동 단계는 짧게 끝내기 |

## 6. 진행 중 결정할 것

- 테스트 프레임워크: 현행 `unittest` 유지(권장) vs `pytest-qt` 도입.
- Windows 스타일: `windows11` vs `fusion`(S1에서 화면 비교 후 결정).
- 작업 공간 이벤트 목록: `QTreeWidget`(빠름) vs `QTreeView` + 모델(드래그·필터에 유리, 권장).
- 미추적 `scripts/mac_capture_bench.py`, `scripts/mac_global_toggle_probe.py` 보존 여부.
