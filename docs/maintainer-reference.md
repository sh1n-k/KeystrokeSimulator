# Maintainer Reference

KeystrokeSimulator는 화면 픽셀/영역을 감시해 키 입력을 실행하는 Python/Tkinter 데스크톱 앱이다. macOS가 주 대상이고 Windows도 지원한다.

## Commands
- 환경 동기화: `uv python install 3.13 && uv sync`
- GUI 실행: `uv run python main.py`
- 인증 포함 GUI 실행: `uv run python main_secure.py`
- 로컬 인증 테스트 서버: `uv run python _local_test_server.py`
- 단위 테스트: `uv run python run_tests.py`
- 조용한 테스트: `uv run python run_tests.py -q`
- GUI 포함 테스트: `RUN_GUI_TESTS=1 uv run python run_tests.py --python <path-to-python> -q`
- 빌드: `uv sync --group build && uv run python _build.py`

## Current Structure
- `main.py`: 표준 GUI 진입점
- `main_secure.py`: 인증 포함 GUI 진입점
- `app/ui/simulator_app.py`: 메인 Tkinter 앱
- `app/core/processor.py`: capture -> match -> conditions -> group priority -> keystrokes 파이프라인
- `app/core/models.py`: `EventModel`, `ProfileModel`, `UserSettings`
- `app/core/capturer.py`: 화면 캡처 스레드
- `app/storage/profile_storage.py`: JSON 저장, 레거시 pickle 로딩/마이그레이션
- `app/storage/profile_display.py`: 프로필 표시 이름 포맷
- `app/ui/profiles.py`: 프로필 관리와 편집 플로우
- `app/ui/event_editor.py`: 상세 이벤트 편집기
- `app/ui/quick_event_editor.py`: 빠른 이벤트 편집기
- `app/ui/event_importer.py`: 이벤트 가져오기
- `app/ui/event_graph.py`: 조건 그래프 렌더링
- `app/ui/modkeys.py`: modification keys 설정
- `app/ui/settings.py`: 사용자 설정 UI
- `app/ui/sort_events.py`: 이벤트 정렬 UI
- `app/utils/i18n.py`: EN/KO 현지화
- `app/utils/runtime_toggle.py`: runtime toggle 정규화와 검증
- `app/utils/system.py`: 시스템 유틸리티
- `app/utils/sounds.py`: 런타임 사운드 재생
- `app/utils/sound_assets.py`: 내장 사운드 상수
- `app/compat/legacy.py`: 레거시 모듈명 매핑의 단일 소스

## Compatibility Rules
- `app/*`만 canonical implementation surface다.
- 루트 `keystroke_*.py`, `i18n.py`, `profile_display.py`, `runtime_toggle_*.py`는 호환용 shim-only다.
- 내부 코드와 테스트는 루트 shim을 import하지 않는다. 이 규칙은 `tests/test_import_conventions.py`가 잡는다.
- 모듈 이동/이름 변경 시 다음 네 곳을 같이 확인한다.
- `app/compat/legacy.py`
- 해당 루트 shim 파일
- `_build.py`
- `app/storage/profile_storage.py`

## Processor Invariants
- 메인 활성화 로직은 `_resolve_effective_states` 중심으로 유지한다.
- 조건 체인은 같은 루프 반복 내에서 strict chain 해석을 유지한다.
- 같은 `group_id`에서는 우선순위 규칙이 유지되어야 한다.
- `execute_action=False` 이벤트는 조건 평가에는 참여하지만 키 입력은 실행하지 않아야 한다.
- runtime toggle 관련 동작은 processor와 simulator app 사이에서 일관되게 유지되어야 한다.

## Profile / Persistence Rules
- 저장 포맷 기본값은 `profiles/*.json`이다.
- 레거시 `profiles/*.pkl`은 계속 로드 가능해야 하고, 실사용 로드 시 JSON으로 마이그레이션되어야 한다.
- `held_screenshot`은 저장되지만 `latest_screenshot`은 저장하지 않는다.
- 새 프로필 또는 fallback 프로필은 `modification_keys` 기본값을 가져야 한다.
- 즐겨찾기 프로필은 장식된 표시 이름을 가질 수 있지만 내부 연산은 canonical 프로필 이름으로 한다.

## UI / Localization Rules
- Tkinter UI 업데이트는 메인 스레드에서만 한다.
- UI 문자열은 `app/utils/i18n.py`의 `txt`, `set_language`, `normalize_language`를 사용한다.
- 기본 언어는 `en`이고 `ko`를 지원한다.
- 폭이 민감한 버튼 텍스트는 가능하면 `dual_text_width(...)`를 사용한다.

## Common Change Checklists

### Adding a New Event Field
1. `app/core/models.py`에서 `EventModel` 갱신
2. `app/ui/event_editor.py` 또는 관련 UI에 필드 추가
3. `app/core/processor.py`에 처리 로직 반영
4. `app/storage/profile_storage.py` 직렬화/역직렬화 호환 점검
5. 관련 테스트 추가

### Adding a New Setting
1. `app/core/models.py`에서 `UserSettings` 갱신
2. `app/ui/settings.py`에 UI 및 저장 로직 반영
3. 필요한 테스트 추가

## Testing Notes
- 표준 검증은 `uv run python run_tests.py -q`다.
- GUI/E2E 검증은 UI/IPC/DB migration/사용자 플로우 영향이 있을 때만 추가한다.
- 새 import 규칙 회귀는 `python3 -m unittest tests.test_import_conventions -q`로 빠르게 확인할 수 있다.

## Build / Auth Notes
- `_build.py`는 `main_secure.py`의 `os.getenv(...)`를 현재 환경값으로 치환한 뒤 PyInstaller를 실행한다.
- 빌드 전 민감한 환경변수 누출 여부를 확인한다.
- `main_secure.py`는 `.env`의 `AUTH_URL`, `VALIDATE_URL`을 사용한다. 실제 URL이나 토큰은 커밋하지 않는다.
