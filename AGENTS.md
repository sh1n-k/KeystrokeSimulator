# AGENTS.md

KeystrokeSimulator는 화면 픽셀/영역을 감시해 키 입력을 실행하는 Python/Tkinter 앱이다. 기본 작업 기준은 `main.py`와 `app/ui/simulator_app.py`를 실행 가능하게 유지하고, `app/core/processor.py`의 조건/그룹/토글 처리와 `profiles/*.json` 및 레거시 `*.pkl` 호환을 깨뜨리지 않는 것이다.

상세 구조, 주요 모듈 역할, 작업 체크리스트는 [docs/maintainer-reference.md](/Users/shin/PersonalProjects/KeystrokeSimulator/docs/maintainer-reference.md)를 본다.

핵심 규칙:
- 구현의 canonical 경로는 `app/*`뿐이다.
- 루트의 `keystroke_*.py`, `i18n.py`, `profile_display.py`, `runtime_toggle_*.py`는 shim-only다. 새 로직을 넣지 말고 내부 코드/테스트도 여기서 import하지 않는다.
- 모듈 이동이나 이름 변경이 생기면 `app/compat/legacy.py`, 루트 shim, `_build.py`, `app/storage/profile_storage.py`를 함께 갱신한다.

Git / 변경 안전장치:
- 문서, 메타데이터, 설정처럼 로직이 바뀌지 않는 작업만 `main`에서 바로 진행한다.
- 그 외 작업은 `main` 직접 작업과 `feature 브랜치 + worktree` 중 무엇으로 진행할지 먼저 확인한다.
- 대규모 rename/migration, formatter 전면 적용, 바이너리 변경, 대량 의존성 업데이트, 삭제 위험 작업은 실행 전에 확인한다.

검증:
- 기본 검증은 `uv run python run_tests.py -q`를 우선한다.
- UI/IPC/DB migration/사용자 플로우에 영향이 있을 때만 필요한 범위의 GUI/E2E 검증을 추가한다.
- 검증을 못 했거나 일부만 했으면 이유와 재현 command를 남긴다.
