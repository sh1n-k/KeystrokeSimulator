# Maintainer Reference

이 문서는 코드 변경 시 함께 확인해야 하는 경계와 불변조건만 기록한다. 실행 및 검증 명령은 루트 [`README.md`](../README.md)와 [`AGENTS.md`](../AGENTS.md)를 기준으로 한다.

## 모듈 경계

UI는 PySide6(Qt) 하나다. 패키지 의존 방향은 `ui` → `presenters` → `engine`·`platform`·`storage` → `domain`이다. Qt 위젯 파일에는 표시와 입력 전달만 두고, 재사용할 계산·검증·상태 경계는 `ui` 밖(주로 `presenters`)에 둔다. presenter는 UI가 구현하는 Host/View 프로토콜만 알고 Qt를 모른다. `tests/test_import_conventions.py`가 다음을 강제한다.

- `tkinter`는 어디서도 import하지 않는다. `PySide6`는 `app/ui/**`에서만 import한다.
- `app/domain`은 `app.engine`·`app.platform`·`app.storage`·`app.ui`와 OS 모듈(Quartz, AppKit, ApplicationServices, ScreenCaptureKit, objc, win32*, mss, pynput, ctypes)을 import하지 않는다.
- `app/engine`·`app/platform`·`app/presenters`·`app/storage`·`app/utils`는 `app.ui`를 import하지 않는다.

| 경로 | 책임 |
| --- | --- |
| `app/__main__.py` | GUI 진입점(`app.ui.application.main`) |
| `app/ui/application.py` | `QApplication` 생성, 로그·예외 훅, 스타일 적용, SIGINT/SIGTERM 종료 |
| `app/ui/main_window.py` | 실행 창(대상·프로세스·수정키 콤보, 상태 배지, 시작 버튼, ⚙ 메뉴) |
| `app/presenters/run_controller.py` | 실행 상태와 입력 동작 조정: listener 연결, 시작/중지, runtime toggle, 준비 상태, 상태 저장 |
| `app/platform/input_router.py` | OS listener 수명, App Nap 응답성 유지, `Dispatcher` 프로토콜(start/post/stop)로 메인 스레드 전달 |
| `app/ui/dispatcher.py` | Qt `Dispatcher`: Signal + QueuedConnection으로 메인 스레드 실행, `stop` 시 세대 번호로 남은 동작 폐기 |
| `app/engine/processor.py` | capture → match → condition → group priority → keystroke 처리 |
| `app/domain/models.py` | `EventModel`, `ProfileModel`, `UserSettings` 계약 |
| `app/engine/capturer.py` | 화면 캡처 스레드 |
| `app/engine/screen_backend.py` | 실행 루프 화면 백엔드. Windows는 mss, macOS는 SCStream |
| `app/engine/capture_session.py` | 캡처 스레드와 편집 UI 사이의 상태 경계 |
| `app/domain/capture_geometry.py` | 캡처 박스·미리보기·돋보기 좌표, HUD 회피 위치, 테두리 사각형, `CaptureResult` |
| `app/domain/capture_render.py` | 대상 픽셀 표시·돋보기 PIL 렌더 |
| `app/presenters/capture_controller.py` | 캡처 HUD 상태와 동작: 단일 모드(작업 공간의 화면 지정), 연속 모드(빠른 이벤트 → Quick 추가), ALT 이동·CTRL 고정 |
| `app/ui/capture_hud.py` | 캡처 HUD 창(항상 위) |
| `app/ui/capture_border.py` | 캡처 영역 테두리(박스 바깥 얇은 창 4개) |
| `app/ui/mac_window.py` | macOS 오버레이 창 level·collectionBehavior(전체화면·다른 Space 위 표시) |
| `app/storage/profile_storage.py` | `profiles/*.json` 직렬화와 호환 로딩, 프로필 표시 순서 |
| `app/storage/modkey_sets_storage.py` | `modkey_sets.json` 수정키 세트 저장 |
| `app/storage/run_sets_storage.py` | `run_sets.json` 이름 있는 실행 세트 저장 |
| `app/domain/profile_events.py` | 이벤트 복사·조건 참조, 신호/규칙 묶음과 표시 순서(=우선순위), 되돌리기 스냅숏, 자동 저장 dirty fingerprint |
| `app/domain/validation.py` | 이름 중복·순환 조건·영역 경계·타이밍 검증, 숫자 입력·시작/중지 키 검증 |
| `app/domain/run_composition.py` | 다중 프로필 실행 시 이벤트/group 네임스페이스 합성 |
| `app/domain/runtime_toggle.py` | 단축키 묶음 trigger 정규화·표시·검증 |
| `app/domain/key_codes.py` | OS별 키 이름↔키 코드 표(`KeyCodes`). OS 호출 없음 |
| `app/platform/keys.py` | `KeyUtils`(`KeyCodes` 상속): 실제 키 눌림 상태 조회(Quartz/`GetAsyncKeyState`) |
| `app/platform/system.py` | 모니터·프로세스·macOS 권한·App Nap 등 OS 서비스 |
| `app/platform/mac_hotkey_tap.py`, `app/platform/mac_key_poll.py` | macOS 전역 단축키 CGEventTap과 폴링 폴백 |
| `app/storage/app_state.py` | `app_state.json`(최근 선택·창 위치) 읽기·쓰기 |
| `app/presenters/workspace_model.py` | 작업 공간 상태와 동작: 프로필·실행 세트 CRUD, 이벤트 편집, 되돌리기, 자동 저장, 실행 중 편집 정책 |
| `app/ui/workspace.py` | 작업 공간 창(사이드바·목록·상세·그래프 탭 배치) |
| `app/ui/workspace_tree.py` | 가운데 목록: 신호/규칙 묶음, 드래그 순서 |
| `app/ui/workspace_detail.py` | 오른쪽 상세 패널: 이벤트 편집, 조건 추가, HUD 캡처 연결, 다중 선택 일괄 동작 |
| `app/ui/workspace_panels.py` | 사이드바, 프로필 헤더(이름·즐겨찾기), 실행 옵션(단축키 묶음), 실행 세트 편집, 그래프 보기 |
| `app/presenters/workspace_sidebar.py` | 사이드바 항목 종류와 항목별 동작 목록(Quick 이름 변경·삭제 없음) |
| `app/presenters/quick_capture.py` | 빠른 이벤트를 Quick 프로필 뒤에 자동 번호로 추가 |
| `app/domain/display_text.py` | 목록 묶음 제목·설명, 조건 요약, 행 배지, 실행 창 콤보 표시 문자열 |
| `app/domain/event_editing.py` | 이벤트 실행 불가 사유, 캡처 적용·지우기, 영역 크기 보정 |
| `app/presenters/settings_form.py`, `app/ui/settings_dialog.py` | 설정 검증·저장과 설정 창 |
| `app/presenters/modkeys_form.py`, `app/ui/modkeys_dialog.py` | 수정키 세트 편집과 편집 창 |
| `app/ui/dialogs.py` | 보조 창 공용 위젯(`KeyCaptureEdit`) |
| `app/domain/event_graph_layout.py` | 조건·그룹 관계 그래프의 노드·간선 구성과 배치 계산 |
| `app/ui/event_graph.py` | 관계 그래프 PIL 렌더링(토큰 색)과 PNG 캐시 |
| `app/utils/i18n.py` | 언어 상태, 언어 정규화와 `txt()` 선택 helper |
| `app/ui/tokens.py` | 툴킷과 무관한 색상·간격·아이콘 토큰 |
| `app/ui/style.py` | Qt 스타일 적용, 상태 배지·시작 버튼 색. 일반 위젯은 플랫폼 기본 스타일과 시스템 라이트/다크를 따른다 |

실제 한국어/영어 UI 문자열은 각 호출부에 두고 `txt()`로 선택한다. 의미 있는 색(상태·테두리)은 호출부에 복제하지 않고 `app/ui/tokens.py`·`app/ui/style.py`를 사용한다.

## Processor 불변조건

- `_resolve_effective_states`가 한 loop 안에서 조건 체인의 유효 상태를 해석한다.
- 같은 `group_id`에서 매칭된 규칙이 여러 개면 `(priority, name)`이 가장 작은 것이 실행된다. 작업 공간 목록은 그룹 안에서 같은 순서로 보이며, 드래그로 순서를 바꿀 때만 그룹 안에서 0부터 `priority`를 다시 쓴다.
- `execute_action=False` 이벤트(UI 용어: 신호)는 조건 평가에는 참여하지만 키 입력을 실행하지 않는다. `execute_action=True`는 규칙이다.
- 화면 좌표가 없는 입력 이벤트는 조건이 하나 이상일 때만 로드하고, raw match를 True로 둔 뒤 기존 조건 AND로 키를 실행한다.
- runtime toggle의 활성 상태와 trigger 처리는 processor와 `RunController` 사이에서 일치해야 한다.
- key press duration과 loop delay는 stop 요청에 응답할 수 있어야 한다.

## 저장 계약

- 프로필의 canonical 저장 형식은 `profiles/*.json`이다.
- `held_screenshot`은 base64 PNG로 저장한다.
- 알 수 없는 JSON 항목은 로딩 실패로 앱 전체를 중단시키지 않으며, 손상된 원본을 자동 덮어쓰지 않는다.
- 수정키 세트는 `modkey_sets.json`에 프로필과 분리 저장한다.
- 이름 있는 실행 세트는 `run_sets.json`에 저장한다. 실행 창은 프로필과 실행 세트를 한 콤보에서 고르며, 프로필을 고르면 `app_state.json`의 `run_set`에 `__current__`를 쓴다(예전 저장값과 같은 형식).
- 최근 선택(프로필·실행 세트), 수정키 세트, 창 위치(메인·작업 공간·캡처 HUD)는 `app_state.json`에 저장한다. 프로필 파일은 편집 단위로 유지하고 실행 시에만 합성한다.
- 실행은 시작 시점에 불러온 프로필을 쓴다. 작업 공간은 실행 중에도 열리며 편집은 다음 시작부터 반영된다. 실행 중에는 프로필 이름 변경·삭제를 막는다.
- 다중 프로필 실행 시 이벤트 이름·group·조건 키는 `{profile}/{token}` 내부 네임스페이스로 격리한다.
- 프로필 JSON의 미사용/legacy 키(`modification_keys`, `independent_thread` 등)는 로드 시 무시하고, `load_profile(migrate=True)` 시 canonical 스키마로 다시 저장해 디스크에서 제거한다.
- 즐겨찾기 장식 문자열은 표시 전용이며 파일 작업에는 canonical 프로필 이름을 사용한다.

## UI 정책

2026-09 UI 개편에서 확정한 결정이다. 바꾸려면 사용자와 먼저 합의한다.

- 캡처 HUD는 게임 화면과 비교하기 위해 topmost를 유지한다. 작업 공간·설정·수정키 창은 topmost가 아니다.
- 캡처 HUD에는 이름만 두고 키칸은 두지 않는다. ALT로 옮긴 위치는 CTRL로 고정하기 전까지 적용되지 않는다.
- 캡처 영역 테두리는 박스 바깥쪽 얇은 창 4개로 그리며 캡처본에 찍히면 안 된다.
- Quick 프로필은 삭제·이름 변경할 수 없다. 빠른 이벤트(연속 캡처)는 Quick 뒤에 자동 번호 이름으로 추가만 하고, 실행을 시작하면 HUD를 닫는다.
- 수정키 세트 선택은 프로필·실행 세트와 독립이다.
- 작업 공간은 자동 저장하며 확인 대화상자 대신 되돌리기를 쓴다. 삭제·순서·일괄 변경·그룹 변경과 캡처 지우기·다시 캡처는 되돌리기 대상이다.
- 키나 화면이 빠진 불완전한 이벤트도 저장하고 배지로 표시한다. 실행 시 로드 단계에서 걸러진다.
- 메인(실행) 창은 Esc로 닫지 않는다. 보조 창은 Esc로 닫는다.

## 변경 체크리스트

| 변경 종류 | 필수 구현 확인 | 최소 자동 테스트 | 필요 E2E |
| --- | --- | --- | --- |
| 이벤트 스키마·복사 | `app/domain/models.py`, `app/domain/profile_events.py` (`EVENT_DIRTY_FIELD_NAMES` / `event_fingerprint`), `app/storage/profile_storage.py`, `app/presenters/workspace_model.py`, `app/ui/workspace_detail.py`, `app/presenters/capture_controller.py`, `app/engine/processor.py` | `test_event_data_conversion.py`, `test_event_copy_sync.py`, `test_profile_json_storage.py`, `test_event_dirty_fingerprint.py` | 캡처·편집 또는 실행 의미가 바뀌면 앱과 프로필, 실제 실행 |
| 작업 공간 목록·순서 | `app/domain/profile_events.py`, `app/domain/display_text.py`, `app/presenters/workspace_model.py`, `app/ui/workspace_tree.py`, `app/ui/workspace.py` | `test_workspace_order.py`, `test_workspace_model.py`, `test_display_text.py`, `test_qt_workspace.py` | 앱과 프로필, 조건·그룹과 그래프 |
| 설정 | `UserSettings` (incl. `notification_sound_pack`, `runtime_toggle_sound_pack`, `runtime_toggle_sound_enabled`), `app/storage/settings_storage.py`, `app/presenters/settings_form.py`, `app/ui/settings_dialog.py`, `app/utils/sounds.py` / `notification_sound_packs.py`, 설정 소비 경로 | `test_settings_storage.py`, `test_settings_form.py`, `test_qt_settings_dialog.py`, `test_notification_sound_packs.py`, `test_keystroke_sounds.py` | 표시·재시작 복원·실행 동작이 바뀌면 설정과 복원 |
| runtime toggle(단축키 묶음) | 모델·저장 필드, `app/domain/runtime_toggle.py`, `app/ui/workspace_panels.py`, `app/ui/workspace_detail.py`, `app/presenters/run_controller.py`, `app/engine/processor.py` | `test_profile_json_storage.py`, `test_resolve_effective_states.py`, `test_condition_and_core_logic.py`, `test_run_controller.py` | 실제 실행; Windows system/hotkey 변경은 Windows 필수 |
| 프로필 경로·저장 | `app/storage/profile_storage.py`, `app/storage/profile_display.py`, `app/ui/main_window.py`, `app/presenters/workspace_model.py` | `test_profile_json_storage.py`, `test_profile_display.py`, `test_qt_main_window.py`, `test_workspace_model.py` | 앱과 프로필 |
| 캡처 UI | `app/engine/capturer.py`, `app/engine/capture_session.py`, `app/domain/capture_geometry.py`, `app/domain/capture_render.py`, `app/domain/event_editing.py`, `app/presenters/capture_controller.py`, `app/ui/capture_hud.py`, `app/ui/capture_border.py`, `app/ui/workspace_detail.py`, processor 입력 형식 | `test_capturer.py`, `test_capture_session.py`, `test_capture_geometry.py`, `test_capture_controller.py`, `test_qt_capture_hud.py`, `test_event_editing.py`, `test_extract_roi_and_capture.py` | 앱과 프로필, 실제 화면 캡처 |
| OS listener·권한 | `app/platform/input_router.py`, `app/ui/dispatcher.py`, `app/presenters/run_controller.py`, `app/platform/system.py`, 관련 설정과 main-thread UI 갱신 | `test_input_router.py`, `test_run_controller.py`, `test_mac_key_poll.py`, `test_keystroke_utils.py` | 실제 실행; 변경 대상 OS에서 수행하고 Windows system/hotkey 변경은 Windows 필수 |

표의 자동 테스트는 시작점이다. Qt 위젯 테스트는 `tests/qt_support.py`가 `QT_QPA_PLATFORM=offscreen`으로 실행하므로 실제 창 배치·항상 위·전체화면 위 표시·포커스는 E2E로 확인한다. 공용 계약을 추가로 건드렸다면 해당 구현을 직접 검증하는 기존 테스트까지 확장한다.
