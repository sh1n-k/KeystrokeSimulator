# Maintainer Reference

이 문서는 코드 변경 시 함께 확인해야 하는 경계와 불변조건만 기록한다. 실행 및 검증 명령은 루트 [`README.md`](../README.md)와 [`AGENTS.md`](../AGENTS.md)를 기준으로 한다.

## 모듈 경계

| 경로 | 책임 |
| --- | --- |
| `app/__main__.py` | GUI 진입점과 예외 로깅 |
| `app/ui/simulator_app.py` | 메인 창, 실행 상태와 입력 동작 조정 |
| `app/ui/main_frames.py` | 메인 창의 프로세스·프로필·도구 프레임 |
| `app/ui/input_listener_session.py` | OS listener 수명과 Tk 메인 스레드 action queue |
| `app/core/processor.py` | capture → match → condition → group priority → keystroke 처리 |
| `app/core/models.py` | `EventModel`, `ProfileModel`, `UserSettings` 계약 |
| `app/core/capturer.py` | 화면 캡처 스레드 |
| `app/ui/capture_session.py` | 캡처 스레드와 편집 UI 사이의 상태 경계 |
| `app/storage/profile_storage.py` | `profiles/*.json` 직렬화와 호환 로딩 |
| `app/ui/event_editor.py` | 상세 이벤트 편집 |
| `app/ui/quick_event_editor.py` | Quick 프로필 캡처 |
| `app/core/profile_events.py` | 이벤트 복사·조건 참조·정렬 연산 |
| `app/ui/profiles.py` | 프로필 창 조정과 저장 |
| `app/ui/profile_event_list.py` | 이벤트 행·목록과 편집 동작 |
| `app/ui/profile_groups.py` | 그룹 선택·관리 UI |
| `app/ui/profile_settings.py` | 프로필 메타·runtime toggle 설정 UI |
| `app/ui/profile_graph_viewer.py` | 프로필 그래프 창 |
| `app/ui/event_graph.py` | 조건·그룹 관계 표시 |
| `app/utils/i18n.py` | 언어 상태, 언어 정규화와 `txt()` 선택 helper |
| `app/ui/theme.py` | UI 색상, 폰트, 간격, 아이콘 토큰 |

실제 한국어/영어 UI 문자열은 각 호출부에 두고 `txt()`로 선택한다. 공통 색상·폰트·간격은 호출부에 복제하지 않고 `app/ui/theme.py`의 토큰을 사용한다.

## Processor 불변조건

- `_resolve_effective_states`가 한 loop 안에서 조건 체인의 유효 상태를 해석한다.
- 같은 `group_id`에서 매칭된 이벤트가 여러 개면 낮은 `priority`가 우선한다.
- `execute_action=False` 이벤트는 조건 평가에는 참여하지만 키 입력을 실행하지 않는다.
- runtime toggle의 활성 상태와 trigger 처리는 processor와 simulator app 사이에서 일치해야 한다.
- key press duration과 loop delay는 stop 요청에 응답할 수 있어야 한다.

## 저장 계약

- 프로필의 canonical 저장 형식은 `profiles/*.json`이다.
- `held_screenshot`은 base64 PNG로 저장한다.
- 알 수 없는 JSON 항목은 로딩 실패로 앱 전체를 중단시키지 않으며, 손상된 원본을 자동 덮어쓰지 않는다.
- 새 프로필과 fallback 프로필은 유효한 `modification_keys` 기본값을 가진다.
- 즐겨찾기 장식 문자열은 표시 전용이며 파일 작업에는 canonical 프로필 이름을 사용한다.

## 변경 체크리스트

| 변경 종류 | 필수 구현 확인 | 최소 자동 테스트 | 필요 E2E |
| --- | --- | --- | --- |
| 이벤트 스키마·복사/import | `app/core/models.py`, `app/core/profile_events.py`, `app/storage/profile_storage.py`, `app/ui/event_editor.py`, `app/ui/quick_event_editor.py`, `app/ui/event_importer.py`, `app/ui/profile_event_list.py`, `app/core/processor.py` | `test_event_data_conversion.py`, `test_event_copy_sync.py`, `test_profile_json_storage.py` | 캡처·편집 또는 실행 의미가 바뀌면 앱과 프로필, 실제 실행 |
| 설정 | `UserSettings`, `app/storage/settings_storage.py`, `app/ui/settings.py`, 설정 소비 경로 | `test_settings_storage.py`, `test_keystroke_settings.py` | 표시·재시작 복원·실행 동작이 바뀌면 설정과 복원 |
| runtime toggle | 모델·저장 필드, `app/utils/runtime_toggle.py`, `app/ui/profile_settings.py`, `app/ui/profile_event_list.py`, `app/ui/simulator_app.py`, `app/core/processor.py` | `test_profile_json_storage.py`, `test_resolve_effective_states.py`, `test_condition_and_core_logic.py`, `test_keystroke_simulator_app_flow.py` | 실제 실행; Windows system/hotkey 변경은 Windows 필수 |
| 프로필 경로·저장 | `app/storage/profile_storage.py`, `app/storage/profile_display.py`, 프로필 선택·편집 호출부 | `test_profile_json_storage.py`, `test_profile_display.py`, 필요 시 `test_keystroke_simulator_app_flow.py` | 앱과 프로필 |
| 캡처 UI | `app/core/capturer.py`, `app/ui/capture_session.py`, `app/ui/event_editor.py` 또는 `app/ui/quick_event_editor.py`, processor 입력 형식 | `test_capturer.py`, `test_capture_session.py`, `test_event_editor_validation.py` 또는 `test_quick_event_editor.py`, `test_extract_roi_and_capture.py` | 앱과 프로필, 실제 화면 캡처 |
| OS listener·권한 | `app/ui/input_listener_session.py`, `app/ui/simulator_app.py`, `app/utils/system.py`, 관련 설정과 main-thread UI 갱신 | `test_input_listener_session.py`, `test_keystroke_simulator_app_flow.py`, `test_keystroke_utils.py` | 실제 실행; 변경 대상 OS에서 수행하고 Windows system/hotkey 변경은 Windows 필수 |

표의 자동 테스트는 시작점이다. 공용 계약을 추가로 건드렸다면 해당 구현을 직접 검증하는 기존 테스트까지 확장한다.
