# Manual E2E Test Plan

자동 테스트로 대체할 수 없는 실제 화면 캡처, OS 권한, 키 입력 hook과 GUI 흐름만 수동 검증합니다. 변경된 영역의 시나리오만 실행하고 결과를 `PASS / FAIL / N/A`로 기록합니다.

Windows system/hotkey 동작을 변경했다면 Windows 실환경 검증은 필수입니다.

## 준비

- macOS 또는 Windows 실사용 환경
- `uv sync` 후 `uv run -m app` 실행 가능
- macOS의 화면 기록 및 손쉬운 사용 권한 허용
- `Quick` 프로필과 삭제 가능한 테스트 프로필 준비
- 색상 변화를 직접 통제할 수 있는 화면 영역 준비

## 앱과 프로필

- 적용 변경: 프로필 경로·저장, 이벤트 편집·복사/import, 캡처 UI
- 대상 OS: macOS 또는 Windows

1. 앱을 실행해 Process, Profile, Start, Quick Events, Settings, ModKeys, Edit Profile 버튼을 확인하고, Edit Profile을 열어 Graph 버튼을 확인한다.
2. 프로필을 복사한 뒤 복사본을 삭제하고 유효한 프로필로 선택이 복구되는지 확인한다.
3. 이벤트를 추가·수정하고 창과 앱을 다시 열어 JSON 저장 결과가 유지되는지 확인한다.
4. `Quick Events`에서 좌표와 이미지를 캡처하고 `Quick` 프로필에 반영되는지 확인한다.

기대 결과: 창이 예외 없이 열리고 프로필 선택, 자동 저장, 복사·삭제가 일관되게 동작한다.

## 조건, 그룹과 그래프

- 적용 변경: 이벤트 스키마, 조건·그룹·그래프, 저장 검증
- 대상 OS: macOS 또는 Windows

1. 조건 평가 전용 이벤트를 만든다.
2. 실행 이벤트 두 개를 같은 그룹에 서로 다른 priority로 구성하고 하나에 조건을 연결한다.
3. Graph에서 조건 방향과 그룹 관계를 확인한다.
4. 중복 이름, 필수 키 누락, 순환 조건을 저장하려 할 때 차단되는지 확인한다.

기대 결과: 설정과 그래프가 일치하고 잘못된 이벤트 구성이 저장되지 않는다.

## 실제 실행

- 적용 변경: processor, runtime toggle, 캡처, OS listener·권한
- 대상 OS: 변경 대상 OS. Windows system/hotkey 변경은 Windows 필수

1. 유효한 프로세스와 프로필을 선택하고 Start/Stop을 두 번 반복한다.
2. 통제 가능한 픽셀 또는 영역 변화로 이벤트를 한 번 발생시킨다.
3. 키 입력 횟수, 그룹 priority와 runtime toggle 동작을 확인한다.
4. 실행 중 UI가 응답하며 Stop 후 입력과 캡처가 중단되는지 확인한다.

기대 결과: 중복 실행이나 무응답 없이 매칭 이벤트만 실행되고 Stop이 즉시 반영된다.

## 설정과 복원

- 적용 변경: 설정 저장·소비, 언어, ModKeys, 창 상태 복원
- 대상 OS: macOS 또는 Windows. Windows system/hotkey 설정 변경은 Windows 필수

1. 언어, key pressed time, loop delay를 변경하고 재실행 후 복원되는지 확인한다.
2. ModKeys 설정을 변경해 실제 키 입력에 반영되는지 확인한다.
3. 보조 창 위치를 변경하고 다시 열었을 때 화면 밖으로 벗어나지 않는지 확인한다.

## 기록

```text
Scenario:
Environment: macOS/Windows, Python version, permissions
Result: PASS / FAIL / N/A
Notes:
Screenshot/Log:
```
