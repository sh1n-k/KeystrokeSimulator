# AGENTS.md

KeystrokeSimulator는 화면 픽셀/영역을 감시해 키 입력을 실행하는 Python/PySide6(Qt) 앱이다. 작업 시 `app/__main__.py`와 `app/ui/main_window.py`를 실행 가능하게 유지하고, `app/engine/processor.py`의 조건·그룹·runtime toggle 처리와 `profiles/*.json` 저장 계약을 보존한다.

상세 모듈 경계와 변경 체크리스트는 [`docs/maintainer-reference.md`](docs/maintainer-reference.md)를 본다.

## 구현 규칙

- canonical 구현 경로는 `app/*`뿐이다.
- 패키지 경계(`domain` 순수 로직, `engine` 실행 엔진, `platform` OS 서비스, `storage` 파일 저장, `presenters` 툴킷 무관 화면 상태·동작, `ui` Qt 위젯)는 `tests/test_import_conventions.py`가 강제한다. `PySide6`는 `app/ui`에서만 import하고 `tkinter`는 쓰지 않는다. 화면 로직은 `presenters`에 두고 위젯은 표시와 입력 전달만 한다.
- 제거된 루트 레거시 모듈명(`main`, `keystroke_*`, `i18n`, `profile_display`, `runtime_toggle_*`)은 다시 만들거나 import하지 않는다.
- 기존 구조와 공개 동작을 우선 보존하고, 요청에 필요하지 않은 래퍼·옵션·추상화는 추가하지 않는다.
- 이벤트 필드 변경 시 모델, 저장소, 편집 UI, processor와 관련 테스트를 함께 확인한다.
- 언어 상태와 `txt()` 선택 helper는 `app/utils/i18n.py`, 실제 UI 문자열은 각 호출부에 둔다. 일반 위젯은 플랫폼 기본 스타일과 시스템 라이트/다크를 따르고, 의미 있는 색은 `app/ui/tokens.py`·`app/ui/style.py`를 source of truth로 사용한다.
- Qt 위젯 변경은 메인 스레드에서 수행한다. listener·캡처 스레드는 `InputRouter.post`(Qt 구현 `app/ui/dispatcher.py`)로 넘긴다.

## 변경 안전장치

- 처음 파일이나 Git 상태를 변경하기 전에 현재 브랜치와 사용자 변경사항을 확인한다.
- 문서·메타데이터·설정만 바꾸는 경우에만 `main`에서 바로 작업한다. 로직 변경은 `main` 직접 작업과 feature branch/worktree 중 어느 방식인지 먼저 확인한다.
- 대규모 rename/migration, formatter 전면 적용, 바이너리 변경, 대량 의존성 업데이트, 삭제 위험 작업은 실행 전에 확인한다.
- 시크릿, 토큰, 키, 개인정보를 출력하거나 커밋하지 않는다.

## 검증

- 기본 검증: `uv run -m scripts.verify`
- 빠른 정적 검증: `uv run -m scripts.verify --static-only`
- 로컬 훅: `uv run pre-commit run --all-files`
- 실제 OS hook, 화면 캡처, GUI 흐름 영향이 있을 때만 [`tests/E2E_TESTPLAN.md`](tests/E2E_TESTPLAN.md)의 관련 항목을 추가로 확인한다.
- 검증을 일부만 실행했으면 이유와 재현 명령을 결과에 남긴다.
