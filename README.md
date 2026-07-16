# Keystroke Simulator

화면의 픽셀 또는 영역을 감시하고 조건이 충족되면 지정한 키 입력을 실행하는 Python/Tkinter 데스크톱 앱입니다. macOS를 주 대상으로 하며 Windows도 지원합니다.

## 주요 기능

- 픽셀 및 영역 색상 매칭과 반전 매칭
- 이벤트 조건 체인과 순환 참조 검증
- 같은 그룹 안에서 낮은 `priority`를 우선하는 상호 배타 실행
- 조건 평가 전용 이벤트와 runtime toggle
- JSON 프로필 저장, 복사, 삭제, 가져오기, 즐겨찾기
- 이벤트 관계 그래프와 한국어/영어 UI

## 실행

요구사항은 `uv`와 Tk/Tcl을 포함한 Python 3.13입니다. 플랫폼별 패키지는 `pyproject.toml`과 `uv.lock`을 기준으로 설치됩니다.

```bash
uv python install 3.13
uv sync
uv run -m app
```

macOS에서는 화면 기록과 손쉬운 사용 권한이 필요합니다.

## 검증

```bash
uv run -m scripts.verify
uv run -m scripts.verify --static-only
uv run pre-commit run --all-files
```

수동 OS 검증이 필요한 변경은 [`tests/E2E_TESTPLAN.md`](tests/E2E_TESTPLAN.md)를 따릅니다. 유지보수 구조와 변경 불변조건은 [`docs/maintainer-reference.md`](docs/maintainer-reference.md)에 정리되어 있습니다.

## 라이선스

MIT — [`LICENSE`](LICENSE)
