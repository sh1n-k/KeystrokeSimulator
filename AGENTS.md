# AGENTS.md

KeystrokeSimulator는 화면 픽셀/영역을 감시해 키 입력을 실행하는 Python/Tkinter 앱이다. 작업 시 `app/__main__.py`와 `app/ui/simulator_app.py`를 실행 가능하게 유지하고, `app/core/processor.py`의 조건·그룹·runtime toggle 처리와 `profiles/*.json` 저장 계약을 보존한다.

상세 모듈 경계와 변경 체크리스트는 [`docs/maintainer-reference.md`](docs/maintainer-reference.md)를 본다.

## 구현 규칙

- canonical 구현 경로는 `app/*`뿐이다.
- 제거된 루트 레거시 모듈명(`main`, `keystroke_*`, `i18n`, `profile_display`, `runtime_toggle_*`)은 다시 만들거나 import하지 않는다.
- 기존 구조와 공개 동작을 우선 보존하고, 요청에 필요하지 않은 래퍼·옵션·추상화는 추가하지 않는다.
- 이벤트 필드 변경 시 모델, 저장소, 편집 UI, processor와 관련 테스트를 함께 확인한다.
- UI 문자열은 `app/utils/i18n.py`, 색상·폰트·간격은 `app/ui/theme.py`를 source of truth로 사용한다.
- Tkinter 위젯 변경은 메인 스레드에서 수행한다.

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
