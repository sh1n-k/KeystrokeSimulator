# Keystroke Simulator

짧은 작업 부트로더:
- 실행: `uv run python main.py`
- 인증 포함 실행: `uv run python main_secure.py`
- 테스트: `uv run python run_tests.py -q`
- 빌드: `uv sync --group build && uv run python scripts/build_secure.py`
- 루트 래퍼: `./build_secure.command`(macOS), `build_secure.cmd`(Windows)

작업 원칙:
- 내부 구현과 테스트는 `app.*`를 canonical import로 사용한다.
- 제거된 루트 레거시 모듈명은 다시 추가하거나 import하지 않는다.
- 구조 변경 시 `scripts/build_secure.py` hidden import와 `app/storage/profile_storage.py`의 JSON 저장 경로를 같이 본다.
- 상세 구조와 변경 체크리스트는 [docs/maintainer-reference.md](/Users/shin/PersonalProjects/KeystrokeSimulator/docs/maintainer-reference.md)를 참조한다.
