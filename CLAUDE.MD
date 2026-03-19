# Keystroke Simulator

짧은 작업 부트로더:
- 실행: `uv run python main.py`
- 인증 포함 실행: `uv run python main_secure.py`
- 테스트: `uv run python run_tests.py -q`
- 빌드: `uv sync --group build && uv run python _build.py`

작업 원칙:
- 내부 구현과 테스트는 `app.*`를 canonical import로 사용한다.
- 루트 `keystroke_*.py` 계열은 외부 호환용 shim이다.
- 구조 변경 시 `app/compat/legacy.py`, 루트 shim, `_build.py` hidden import, `app/storage/profile_storage.py`의 legacy pickle 경로를 같이 본다.
- 상세 구조와 변경 체크리스트는 [docs/maintainer-reference.md](/Users/shin/PersonalProjects/KeystrokeSimulator/docs/maintainer-reference.md)를 참조한다.
