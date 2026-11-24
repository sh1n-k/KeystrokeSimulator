# Maintainer Reference

이 문서는 코드 변경 시 함께 확인해야 하는 경계와 불변조건만 기록한다. 실행 및 검증 명령은 루트 [`README.md`](../README.md)와 [`AGENTS.md`](../AGENTS.md)를 기준으로 한다.

## 모듈 경계

UI는 PySide6(Qt) 하나다. 패키지 의존 방향은 `ui` → `presenters` → `engine`·`platform`·`storage` → `domain`이다. Qt 위젯 파일에는 표시와 입력 전달만 두고, 재사용할 계산·검증·상태 경계는 `ui` 밖(주로 `presenters`)에 둔다. presenter는 UI가 구현하는 Host/View 프로토콜만 알고 Qt를 모른다. `tests/test_import_conventions.py`가 다음을 강제한다.

- `tkinter`는 어디서도 import하지 않는다. `PySide6`는 `app/ui/**`에서만 import한다.
- `app/domain`은 `app.engine`·`app.platform`·`app.storage`·`app.ui`와 OS 모듈(Quartz, AppKit, ApplicationServices, ScreenCaptureKit, objc, win32*, mss, pynput, ctypes)을 import하지 않는다.
- `app/engine`·`app/platform`·`app/presenters`·`app/storage`·`app/utils`는 `app.ui`를 import하지 않는다.
- 문자열 리터럴로 부르는 `importlib.import_module("X")`·`__import__("X")`도 import로 검사한다. 모듈 이름을 변수로 받는 동적 import는 `app/platform/system.py`·`app/engine/screen_backend.py`에서만 허용한다(`NON_LITERAL_DYNAMIC_IMPORT_ALLOWLIST`).

| 경로 | 책임 |
| --- | --- |
| `app/__main__.py` | GUI 진입점(`app.ui.application.main`) |
| `app/ui/application.py` | `QApplication` 생성, 앱 아이콘(`app/ui/assets/app_icon.svg`) 적용, 로그·예외 훅, 스타일 적용, SIGINT/SIGTERM 종료 |
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
| `app/domain/profile_events.py` | 이벤트 복사·조건 참조, 상태/동작 묶음과 표시 순서(=우선순위), 되돌리기 스냅숏, 자동 저장 dirty fingerprint |
| `app/domain/validation.py` | 이름 중복·순환 조건·영역 경계·타이밍 검증, 숫자 입력·시작/중지 키 검증 |
| `app/domain/run_composition.py` | 다중 프로필 실행 시 이벤트/group 네임스페이스 합성 |
| `app/domain/runtime_toggle.py` | 단축키 묶음 trigger 정규화·표시·검증 |
| `app/domain/key_codes.py` | OS별 키 이름↔키 코드 표(`KeyCodes`). OS 호출 없음 |
| `app/platform/keys.py` | `KeyUtils`(`KeyCodes` 상속): 실제 키 눌림 상태 조회(Quartz/`GetAsyncKeyState`) |
| `app/platform/system.py` | 모니터·프로세스·macOS 권한·App Nap·Windows AppUserModelID(작업 표시줄 아이콘) 등 OS 서비스 |
| `app/platform/mac_hotkey_tap.py`, `app/platform/mac_key_poll.py` | macOS 전역 단축키 CGEventTap과 폴링 폴백 |
| `app/storage/app_state.py` | `app_state.json`(최근 선택·창 위치) 읽기·쓰기 |
| `app/presenters/workspace_model.py` | 작업 공간 상태와 동작: 프로필·실행 세트 CRUD, 이벤트 편집, 되돌리기, 자동 저장, 실행 중 편집 정책 |
| `app/ui/workspace.py` | 작업 공간 창(사이드바·목록·상세·그래프 탭 배치) |
| `app/ui/workspace_tree.py` | 가운데 목록: 상태/동작 묶음, 드래그 순서 |
| `app/ui/workspace_detail.py` | 오른쪽 상세 패널: 이벤트 편집, 조건 추가, HUD 캡처 연결, 다중 선택 일괄 동작(사용·단축키 묶음·그룹·조건 추가/변경/제거, 조건 행렬·요약 표) |
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
| `app/utils/sounds.py`, `app/utils/notification_sound_packs.py` | 알림음 재생(miniaudio)과 사운드 팩 정의·선택 |
| `app/utils/_classic_notification_sounds.py`, `app/utils/_soft_notification_sounds.py`, `app/utils/_toggle_notification_sounds.py`, `app/utils/sound_assets.py` | base64 오디오만 담은 데이터 모듈. 손으로 고치지 않는다(soft 계열은 `uv run -m scripts.generate_soft_notification_sounds`로 생성). 한 줄이 수만 자라 `.rgignore`로 ripgrep 검색에서 뺐다 |
| `app/utils/exception_hooks.py` | 처리되지 않은 예외(메인·스레드)를 로그로 남기는 훅 |
| `app/storage/json_objects.py` | JSON 객체를 문자열 키 dict로 바꾸는 저장소 공용 helper |
| `app/ui/tokens.py` | 툴킷과 무관한 색상·간격·아이콘 토큰 |
| `app/ui/style.py` | Qt 스타일 적용, 상태 배지·시작 버튼 색. 일반 위젯은 플랫폼 기본 스타일과 시스템 라이트/다크를 따른다 |

실제 한국어/영어 UI 문자열은 각 호출부에 두고 `txt()`로 선택한다. 의미 있는 색(상태·테두리)은 호출부에 복제하지 않고 `app/ui/tokens.py`·`app/ui/style.py`를 사용한다.

## Processor 불변조건

- `_resolve_effective_states`가 한 loop 안에서 조건 체인의 유효 상태를 해석한다.
- 같은 `group_id`에서 매칭된 동작이 여러 개면 `(priority, name)`이 가장 작은 것이 실행된다. 작업 공간 목록은 그룹 안에서 같은 순서로 보이며, 드래그로 순서를 바꿀 때만 그룹 안에서 0부터 `priority`를 다시 쓴다.
- `execute_action=False` 이벤트(UI 용어: 상태)는 조건 평가에는 참여하지만 키 입력을 실행하지 않는다. `execute_action=True`는 동작이다(UI 용어). 코드 식별자(`signal`, `rule`)는 그대로 둔다.
- `wait_action=True` 동작(UI: 키 드롭다운의 "대기")은 그룹 선택에는 참여하지만 키를 누르지 않는다. 그룹에서 선택되면 그 루프에는 아래 동작이 실행되지 않으므로, 상위 동작이 자원을 기다리는 동안 하위 동작이 끼어들지 않게 막는 데 쓴다. 대기와 `key_to_enter`는 둘 중 하나만 저장한다.
- 화면 좌표가 없는 이벤트(`EventModel.is_screenless_input`)는 조건이 하나 이상일 때만 로드하고, raw match를 True로 둔 뒤 기존 조건 AND로 판정한다. 동작이면 키를 실행하고, 상태면 파생 상태(`is_derived_state`, 목록 배지 "파생")로서 다른 이벤트의 조건으로만 쓰인다. 공통 조건을 파생 상태 하나로 묶어 여러 동작이 참조하게 하는 용도다.
- 이벤트를 실행에 로드할 수 있는지는 `EventModel.has_processor_inputs()` 하나로 판정한다. 실행 창 시작 가능 여부(`events_with_processor_inputs`), processor 로드(`_init_event_data`), 작업 공간 배지(`event_issues`)가 이 기준을 함께 쓰며 `tests/test_processor_inputs_consistency.py`가 일치를 검사한다. 영역 모드는 여기에 더해 processor가 캡처본에서 기준 영역을 잘라낼 수 있어야 로드된다.
- 실행 구성 오류의 종류(중복 이벤트·단축키 묶음)는 `ComposedRunSession.error_kind`로 판단한다. 오류 문구를 문자열로 검사해 분기하지 않는다.
- runtime toggle의 활성 상태와 trigger 처리는 processor와 `RunController` 사이에서 일치해야 한다.
- key press duration과 loop delay는 stop 요청에 응답할 수 있어야 한다.

## 저장 계약

- 프로필의 canonical 저장 형식은 `profiles/*.json`이다.
- `held_screenshot`은 base64 PNG로 저장한다.
- 이벤트의 `conditions`는 작업 공간 목록 표시 순서(상태 → 그룹별 동작 → 그룹 없는 동작, 묶음 안은 `(priority, name)`)로 정렬해 저장한다. 작업 공간 편집(`WorkspaceModel._changed`)과 다른 프로필로 복사할 때 `sort_conditions_by_display_order`를 적용한다. 변경 감지 fingerprint는 조건 순서를 보지 않으므로 순서만 다른 기존 파일은 다음 실제 편집 때 정렬된다.
- 알 수 없는 JSON 항목은 로딩 실패로 앱 전체를 중단시키지 않으며, 손상된 원본을 자동 덮어쓰지 않는다.
  - `load_profile`은 읽을 수 없는 파일을 빈 프로필로 돌려주므로, 불러와 다시 쓰는 곳은 `profile_file_problem`과 `load_ignored_invalid_data`를 먼저 확인한다.
  - 작업 공간은 손상된 프로필을 열지 않고 오류를 보인 뒤 보던 항목(없으면 Quick)에 머문다. 다른 프로필로 복사할 때 대상이 손상돼 있으면 복사를 거부한다.
  - Quick이 손상됐으면 원본을 `Quick.json.broken-<시각>`으로 옮기고 빈 Quick을 만든다.
- 수정키 세트는 `modkey_sets.json`에 프로필과 분리 저장한다.
- 이름 있는 실행 세트는 `run_sets.json`에 저장한다. 실행 창은 프로필과 실행 세트를 한 콤보에서 고르며, 프로필을 고르면 `app_state.json`의 `run_set`에 `__current__`를 쓴다(예전 저장값과 같은 형식).
- 최근 선택(프로필·실행 세트), 수정키 세트, 창 위치(메인·작업 공간·캡처 HUD)는 `app_state.json`에 저장한다. 프로필 파일은 편집 단위로 유지하고 실행 시에만 합성한다.
- 실행은 시작 시점에 불러온 프로필을 쓴다. 작업 공간은 실행 중에도 열리며 편집은 다음 시작부터 반영된다. 실행 중에는 프로필 이름 변경·삭제를 막는다.
- 작업 공간에서 연 프로필·실행 세트가 실행 창의 실행 대상이 된다. 실행 중에 연 항목은 중지한 뒤 실행 대상이 되며, 시작 직전에 예약된 자동 저장을 먼저 끝낸다.
- 다중 프로필 실행 시 이벤트 이름·group·조건 키는 `{profile}/{token}` 내부 네임스페이스로 격리한다.
- 프로필 JSON의 미사용/legacy 키(`modification_keys`, `independent_thread` 등)는 로드 시 무시하고, `load_profile(migrate=True)` 시 canonical 스키마로 다시 저장해 디스크에서 제거한다.
- 즐겨찾기 장식 문자열은 표시 전용이며 파일 작업에는 canonical 프로필 이름을 사용한다.

## UI 정책

2026-09 UI 개편에서 확정한 결정이다. 바꾸려면 사용자와 먼저 합의한다.

- 캡처 HUD는 게임 화면과 비교하기 위해 topmost를 유지한다. 작업 공간·설정·수정키 창은 topmost가 아니다.
- 캡처 박스와 겹치면 HUD는 박스 바로 옆(같은 모니터 안의 가장 가까운 쪽)으로만 비킨다. ALT로 박스를 옮기는 동안 박스가 원래 자리에서 떨어지면 돌아오고, ALT를 놓은 뒤에는 움직이지 않는다. 위치 저장은 원래 자리 기준이다(2026-10 결정).
- 캡처 HUD에는 이름만 두고 키칸은 두지 않는다. ALT로 옮긴 위치는 CTRL로 고정하기 전까지 적용되지 않는다.
- 캡처 HUD의 크기칸은 고급 밖에 상시 둔다. 미리보기·돋보기 휠은 실시간 화면(고정 전)에서만 비율을 지켜 크기를 바꾸고(고정 후에는 크기칸을 쓴다), 크기칸은 클릭으로만 포커스를 받는다(포커스가 남으면 CTRL이 무시된다). 새 크기 프레임이 오기 전에는 고정하지 않으며, 고정한 뒤에는 화살표로 고른 픽셀을 1px(Shift 10px)씩 옮긴다. 고정 후 위치나 크기를 바꾸면 CTRL로 다시 고정하기 전까지 적용되지 않는다(2026-11 결정).
- 캡처 영역 테두리는 박스 바깥쪽 얇은 창 4개로 그리며 캡처본에 찍히면 안 된다.
- Quick 프로필은 삭제·이름 변경할 수 없다. 빠른 이벤트(연속 캡처)는 Quick 뒤에 자동 번호 이름으로 추가만 하고, 실행을 시작하면 HUD를 닫는다.
- 수정키 세트 선택은 프로필·실행 세트와 독립이다.
- 실행 세트를 고르면 그 세트의 현재 프로필만 실행한다. 남은 멤버가 없으면 마지막 프로필로 대신 실행하지 않고 시작을 막는다(2026-10 결정).
- 작업 공간은 자동 저장하며 확인 대화상자 대신 되돌리기를 쓴다. 삭제·순서·일괄 변경(조건 포함)·그룹 변경과 캡처 지우기·다시 캡처는 되돌리기 대상이다.
- 일괄 조건 추가·변경은 자기 자신이거나 순환이 생기는 이벤트를 건너뛰고 건너뛴 수를 상태 줄에 알린다. 바뀐 이벤트가 없으면 되돌리기 항목을 남기지 않는다.
- 화면 지우기나 일괄 조건 추가·행렬 칸 전환으로 화면 없는 상태가 파생 상태가 되면(실행에 로드되어 조건이 맞으면 켜짐) 상태 줄에 알린다.
- 다중 선택 조건 표는 선택이 `BULK_MATRIX_MAX_EVENTS`(5)개 이하면 조건×이벤트 행렬(칸을 누르면 그 이벤트만 켜짐 → 꺼짐 → 없음, 칸마다 되돌리기 한 단계), 넘으면 켜짐·꺼짐·없음 개수 요약 표로 바뀐다. 이벤트마다 값이 다르거나 빠진 조건 이름은 warn 색으로 칠한다. 색은 `style.status_colors`(켜짐 ready, 꺼짐 error)를 쓴다.
- 키나 화면이 빠진 불완전한 이벤트도 저장하고 배지로 표시한다. 실행 시 로드 단계에서 걸러진다.
- 메인(실행) 창은 Esc로 닫지 않는다. 보조 창은 Esc로 닫는다.
- 대상 앱은 "이름 (PID)"로 고른다. 시작 직전과 대상 목록을 열 때 목록을 다시 읽고(`match_process_index`), 같은 PID가 있으면 유지하고, 없으면 같은 이름이 하나일 때만 새 PID로 따라간다. 같은 이름이 없거나 여럿이면 선택을 비워 시작을 막는다(같은 이름의 여러 인스턴스 중 하나를 지정하는 경우를 지키기 위해 이름만으로 비교하지 않는다). 실행 중에 대상 앱을 재시작하는 경우는 따라가지 않는다(2026-11 결정).
- 저장된 대상 앱(`app_state.json`의 `process`, 이름만)이 꺼진 채 앱을 켜면 다른 앱을 고르지 않고 선택을 비운 채 "이름 (실행 중 아님)"을 placeholder로 보인다. 그 이름은 위 규칙으로 시작 직전·목록 열기·실행 창이 다시 활성화될 때(선택이 비었고 실행 중이 아닐 때만) 따라간다(2026-11 결정).

## 변경 체크리스트

| 변경 종류 | 필수 구현 확인 | 최소 자동 테스트 | 필요 E2E |
| --- | --- | --- | --- |
| 이벤트 스키마·복사 | `app/domain/models.py` (`has_processor_inputs` 포함), `app/domain/profile_events.py` (`EVENT_DIRTY_FIELD_NAMES` / `event_fingerprint`), `app/storage/profile_storage.py`, `app/presenters/workspace_model.py`, `app/ui/workspace_detail.py`, `app/presenters/capture_controller.py`, `app/engine/processor.py` | `test_event_data_conversion.py`, `test_event_copy_sync.py`, `test_profile_json_storage.py`, `test_event_dirty_fingerprint.py`, `test_processor_inputs_consistency.py` | 캡처·편집 또는 실행 의미가 바뀌면 앱과 프로필, 실제 실행 |
| 작업 공간 목록·순서 | `app/domain/profile_events.py`, `app/domain/display_text.py`, `app/presenters/workspace_model.py`, `app/ui/workspace_tree.py`, `app/ui/workspace.py` | `test_workspace_order.py`, `test_workspace_model.py`, `test_display_text.py`, `test_qt_workspace.py` | 앱과 프로필, 조건·그룹과 그래프 |
| 설정 | `UserSettings` (incl. `notification_sound_pack`, `runtime_toggle_sound_pack`, `runtime_toggle_sound_enabled`), `app/storage/settings_storage.py`, `app/presenters/settings_form.py`, `app/ui/settings_dialog.py`, `app/utils/sounds.py` / `notification_sound_packs.py`, 설정 소비 경로 | `test_settings_storage.py`, `test_settings_form.py`, `test_qt_settings_dialog.py`, `test_notification_sound_packs.py`, `test_keystroke_sounds.py` | 표시·재시작 복원·실행 동작이 바뀌면 설정과 복원 |
| runtime toggle(단축키 묶음) | 모델·저장 필드, `app/domain/runtime_toggle.py`, `app/ui/workspace_panels.py`, `app/ui/workspace_detail.py`, `app/presenters/run_controller.py`, `app/engine/processor.py` | `test_profile_json_storage.py`, `test_resolve_effective_states.py`, `test_condition_and_core_logic.py`, `test_run_controller.py` | 실제 실행; Windows system/hotkey 변경은 Windows 필수 |
| 프로필 경로·저장 | `app/storage/profile_storage.py`, `app/storage/profile_display.py`, `app/ui/main_window.py`, `app/presenters/workspace_model.py` | `test_profile_json_storage.py`, `test_profile_display.py`, `test_qt_main_window.py`, `test_workspace_model.py` | 앱과 프로필 |
| 캡처 UI | `app/engine/capturer.py`, `app/engine/capture_session.py`, `app/domain/capture_geometry.py`, `app/domain/capture_render.py`, `app/domain/event_editing.py`, `app/presenters/capture_controller.py`, `app/ui/capture_hud.py`, `app/ui/capture_border.py`, `app/ui/workspace_detail.py`, processor 입력 형식 | `test_capturer.py`, `test_capture_session.py`, `test_capture_geometry.py`, `test_capture_controller.py`, `test_qt_capture_hud.py`, `test_event_editing.py`, `test_extract_roi_and_capture.py` | 앱과 프로필, 실제 화면 캡처 |
| OS listener·권한 | `app/platform/input_router.py`, `app/ui/dispatcher.py`, `app/presenters/run_controller.py`, `app/platform/system.py`, 관련 설정과 main-thread UI 갱신 | `test_input_router.py`, `test_run_controller.py`, `test_mac_key_poll.py`, `test_keystroke_utils.py` | 실제 실행; 변경 대상 OS에서 수행하고 Windows system/hotkey 변경은 Windows 필수 |

## 테스트·검증 규칙

- `uv run -m scripts.verify`는 unittest를 빈 임시 폴더를 작업 디렉터리로 삼아 실행하고, 끝난 뒤 그 폴더에 파일이 남으면 실패한다. 앱의 저장 경로(`app_state.json`, `user_settings.json`, `run_sets.json`, `modkey_sets.json`, `profiles/`, `logs/`)는 작업 디렉터리 기준 상대경로라서, 테스트는 임시 폴더로 `os.chdir`하거나 임시 경로를 넘겨야 한다. `os.chdir` 복귀는 setUp에서 `addCleanup`으로 등록해(임시 폴더 삭제 바로 다음) 테스트 본문이 등록한 cleanup(창 닫기 → 상태 저장)보다 늦게 돌게 한다. tearDown에서 복귀하면 cleanup이 저장소 루트에서 돈다.
- verify는 테스트 출력에서 loguru 로그와 offscreen Qt 경고를 끈다. 실패 원인을 볼 때는 `LOGURU_LEVEL=DEBUG QT_LOGGING_RULES= uv run -m scripts.verify`처럼 다시 켠다.
- 진단용 환경변수: `KEYSIM_PROFILE_PERF=1`은 프로필 로드·저장 시간과 processor 메인 루프 1회 시간을 `[perf]`로 출력한다. `KEYSIM_WIN_SCANCODE=1`은 Windows 키 입력을 scancode 경로(`KEYEVENTF_SCANCODE`)로 보낸다.

표의 자동 테스트는 시작점이다. Qt 위젯 테스트는 `tests/qt_support.py`가 `QT_QPA_PLATFORM=offscreen`으로 실행하므로 실제 창 배치·항상 위·전체화면 위 표시·포커스는 E2E로 확인한다. 공용 계약을 추가로 건드렸다면 해당 구현을 직접 검증하는 기존 테스트까지 확장한다.
