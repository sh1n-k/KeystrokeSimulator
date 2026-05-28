# E2E Test Plan

이 문서는 자동 테스트만으로 확인하기 어려운 사용자 흐름과 실제 OS 권한 의존 동작을 검증하는 체크리스트입니다. 각 시나리오는 `PASS / FAIL / N/A`로 기록하고, 실패 시 단계 번호, 실제 결과, 스크린샷 또는 로그 경로를 남깁니다.

## 준비

- macOS 또는 Windows 실사용 환경
- `uv sync` 완료
- GUI 실행 가능: `uv run -m app`
- 인증 흐름 검증 시 실행 가능: `uv run -m app.secure`
- macOS라면 Accessibility / Screen Recording 권한 허용
- `Quick` 프로필 유지
- 테스트용 새 프로필 1개 준비: `RefactorTest` 권장
- 화면에서 색상 변화가 확실한 영역 1개 준비

## Track A: CI-Friendly Integration E2E

목표: OS hook(`pynput`)과 capture I/O(`mss`)를 mock 처리하면서 실제 UI 상태 전환과 저장 흐름을 검증합니다.

권장 시나리오:

1. App startup creates/selects `Quick` profile.
2. Profile copy/delete flow keeps canonical profile names.
3. Favorite display label does not break canonical profile operations.
4. Start/Stop toggle updates UI and calls `KeystrokeProcessor.start/stop` exactly once.
5. Empty/invalid profile cannot start simulation.
6. `app.secure` successful auth transitions to main app.
7. `app.secure` invalid session forces app close.
8. Lockout countdown starts once on the 3rd failed auth attempt.

## Track B: Manual Real-Environment E2E

목표: 실제 디스플레이, OS 권한, 외부 인증 환경이 걸린 흐름을 확인합니다.

### A. 앱 시작 / 기본 화면

1. `uv run -m app` 실행
2. 메인 창이 열리는지 확인
3. Process / Profile / Start/Stop / Quick Events / Settings / ModKeys / Edit Profile / Graph 버튼이 보이는지 확인
4. 프로필 목록에 `Quick`가 존재하는지 확인
5. 앱 종료 후 다시 실행

기대 결과: 예외 팝업 없이 창이 열리고, 재실행 후에도 프로필 목록과 주요 버튼이 정상 표시됩니다.

### B. 프로필 생성 / 복사 / 삭제

1. 기존 프로필 하나를 선택
2. `Copy` 클릭
3. 복사된 프로필이 자동 선택되는지 확인
4. 복사본 이름을 `RefactorTest`로 바꾸거나 새 테스트용 이름으로 유지
5. `Delete` 클릭 후 삭제 확인
6. 삭제 뒤 앱이 다른 유효 프로필(`Quick` 등)로 정상 fallback 하는지 확인

기대 결과: 복사본이 생성되고, 삭제 후 깨진 선택 상태가 남지 않으며, 즐겨찾기 표시 이름이 내부 동작을 망치지 않습니다.

### C. Quick Events 저장 흐름

1. `Quick Events` 창 열기
2. 화면의 명확한 위치에 마우스를 올림
3. `Alt`로 좌표 확인
4. `Ctrl`로 이미지 캡처/저장
5. 피드백 문구와 저장 카운트가 증가하는지 확인
6. 창을 닫고 `Edit Profile`에서 `Quick` 프로필 이벤트가 반영됐는지 확인

기대 결과: 좌표와 이미지 캡처가 동작하고, 저장 피드백이 갱신되며, `Quick` 프로필에서 실제 이벤트로 확인됩니다.

### D. 프로필 편집기 생성 / 수정 / 자동 저장

1. 테스트 프로필 선택 후 `Edit Profile` 열기
2. `Add Event`로 새 이벤트 추가
3. 이벤트 이름, 키, 좌표/이미지 캡처를 입력
4. `OK`로 저장
5. 리스트에 새 이벤트가 나타나는지 확인
6. 같은 이벤트를 다시 열어 이름 또는 키를 수정
7. 창을 닫았다가 다시 열어 변경이 유지되는지 확인

기대 결과: 이벤트 추가/수정이 가능하고, 목록이 즉시 갱신되며, 자동 저장 결과가 유지됩니다.

### E. 이벤트 검증 규칙

1. 이벤트 이름을 기존 이벤트와 동일하게 저장 시도
2. 실행 이벤트에서 Key 없이 저장 시도
3. 영역 모드에서 너무 작은/불가능한 크기 입력 시도
4. 조건 체인에서 순환 참조가 생기도록 구성 시도

기대 결과: 중복 이름, 필수값 누락, 불가능한 영역 크기, 순환 의존이 저장 전에 차단되거나 명확히 처리됩니다.

### F. 조건 / 그룹 / 그래프

1. 조건 전용 이벤트 1개 생성 (`키 입력 실행` 끔)
2. 실행 이벤트 2개를 같은 그룹으로 묶고 priority를 다르게 설정
3. 그중 하나가 조건 전용 이벤트에 의존하도록 설정
4. `Graph` 열기
5. 노드, 화살표, 그룹 표현이 정상인지 확인

기대 결과: 조건/그룹 설정이 저장되고, Graph 창에서 이벤트 관계를 확인할 수 있습니다.

### G. Settings / ModKeys / 상태 복원

1. `Settings` 열기
2. language, key pressed time, delay between loop 값을 변경
3. 창 닫기 후 다시 열어 값이 유지되는지 확인
4. `ModKeys` 열기
5. Alt / Ctrl / Shift 중 하나를 enabled + pass 또는 대체 키로 설정
6. 창 위치를 옮긴 뒤 닫고 다시 열어 위치 복원이 자연스러운지 확인

기대 결과: 설정과 ModKeys 변경이 저장되고, 보조 창 재오픈 시 비정상 위치/초기화 문제가 없습니다.

### H. Start / Stop 기본 실행

1. 유효한 프로세스 선택
2. 유효한 프로필 선택
3. `Start` 클릭
4. 버튼/상태 문구가 실행 중 상태로 바뀌는지 확인
5. `Stop` 클릭
6. 다시 `Start` / `Stop` 반복

기대 결과: Start 직후 앱이 멈추지 않고, Stop 시 정상 종료되며, 반복 실행해도 중복 스레드/중복 시작 증상이 없습니다.

### I. 실제 화면 매칭 1건 스모크

1. 픽셀 매칭 또는 작은 영역 매칭 이벤트 1개 준비
2. 쉽게 통제 가능한 화면 변화 준비
3. `Start` 실행
4. 화면을 매칭 상태로 바꿔 1회 트리거 유도
5. 키 입력이 예상 횟수로 발생하는지 확인
6. 앱이 멈추거나 UI가 얼지 않는지 확인

기대 결과: 이벤트가 실제로 발동하고, 오작동 연타 또는 무반응 없이 앱 UI가 계속 응답합니다.

### J. 인증 진입점

1. `uv run -m app.secure` 실행
2. 로그인/인증 UI가 열리는지 확인
3. 테스트 서버 또는 준비된 인증 환경으로 정상 인증 1회 수행
4. 인증 후 메인 앱으로 전환되는지 확인
5. 실패 인증 3회 시 lockout/countdown 동작 확인

기대 결과: 인증 UI가 열리고, 성공 시 메인 앱으로 전환되며, 실패 시 오류 및 countdown이 중복 없이 한 번만 시작됩니다.

## 회귀 체크 포인트

- 프로필 편집기, Quick Events, Settings, Graph가 모두 열리는지
- 프로필 복사/삭제 후 선택 상태가 깨지지 않는지
- 자동 저장 후 재시작해도 이벤트와 설정이 유지되는지
- Start/Stop을 여러 번 반복해도 중복 실행 증상이 없는지
- `app`와 `app.secure` 두 진입점 모두 열리는지
- 오류 발생 시 앱이 조용히 죽지 않고 사용자에게 피드백을 주는지

## 기록 템플릿

```text
[Scenario]
- Name:
- Environment: macOS/Windows, Python version, permissions granted 여부
- Result: PASS / FAIL / N/A
- Notes:
- Screenshot/Log:
```
