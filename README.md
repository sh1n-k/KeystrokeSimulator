# Keystroke Simulator

화면의 픽셀 또는 영역을 감시하고 조건이 충족되면 지정한 키 입력을 실행하는 Python/Tkinter 데스크톱 앱입니다. macOS를 주 대상으로 하며 Windows도 지원합니다.

## 주요 기능

- 신호(화면 픽셀·영역 감시)와 규칙(조건 조합으로 키 입력)을 나눠 편집하는 작업 공간
- 픽셀·영역 색상 매칭, "색이 다를 때" 매칭
- 조건 체인과 순환 참조 검증
- 같은 그룹 안에서는 목록 위쪽 규칙 하나만 실행(드래그로 순서 변경)
- 항상 위 캡처 HUD와 캡처 영역 테두리, 빠른 이벤트 연속 캡처
- 단축키로 켜고 끄는 이벤트 묶음, 여러 프로필을 함께 실행하는 실행 세트
- JSON 프로필 저장·복사·삭제·즐겨찾기, 다른 프로필로 이벤트 복사, 되돌리기
- 이벤트 관계 그래프와 한국어/영어 UI

## 실행

요구사항은 `uv`와 Tk/Tcl을 포함한 Python 3.14입니다. 플랫폼별 패키지는 `pyproject.toml`과 `uv.lock`을 기준으로 설치됩니다.

```bash
uv python install 3.14
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
