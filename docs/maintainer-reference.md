# Maintainer Reference

이 문서는 코드 변경 시 함께 확인해야 하는 경계와 불변조건만 기록한다. 실행 및 검증 명령은 루트 [`README.md`](../README.md)와 [`AGENTS.md`](../AGENTS.md)를 기준으로 한다.

## 모듈 경계

| 경로 | 책임 |
| --- | --- |
| `app/__main__.py` | GUI 진입점과 예외 로깅 |
| `app/ui/simulator_app.py` | 메인 창, 실행 상태, OS 입력 listener 조정 |
| `app/core/processor.py` | capture → match → condition → group priority → keystroke 처리 |
| `app/core/models.py` | `EventModel`, `ProfileModel`, `UserSettings` 계약 |
| `app/core/capturer.py` | 화면 캡처 스레드 |
| `app/storage/profile_storage.py` | `profiles/*.json` 직렬화와 호환 로딩 |
| `app/ui/event_editor.py` | 상세 이벤트 편집 |
| `app/ui/quick_event_editor.py` | Quick 프로필 캡처 |
| `app/ui/profiles.py` | 프로필 관리와 이벤트 목록 |
| `app/ui/event_graph.py` | 조건·그룹 관계 표시 |
| `app/utils/i18n.py` | 한국어/영어 문자열과 언어 정규화 |
| `app/ui/theme.py` | UI 색상, 폰트, 간격, 아이콘 토큰 |

## Processor 불변조건

- `_resolve_effective_states`가 한 loop 안에서 조건 체인의 유효 상태를 해석한다.
- 같은 `group_id`에서 매칭된 이벤트가 여러 개면 낮은 `priority`가 우선한다.
- `execute_action=False` 이벤트는 조건 평가에는 참여하지만 키 입력을 실행하지 않는다.
- runtime toggle의 활성 상태와 trigger 처리는 processor와 simulator app 사이에서 일치해야 한다.
- key press duration과 loop delay는 stop 요청에 응답할 수 있어야 한다.

## 저장 계약

- 프로필의 canonical 저장 형식은 `profiles/*.json`이다.
- `held_screenshot`은 base64 PNG로 저장한다.
- 알 수 없는 JSON 항목은 로딩 실패로 앱 전체를 중단시키지 않으며, 손상된 원본을 자동 덮어쓰지 않는다.
- 새 프로필과 fallback 프로필은 유효한 `modification_keys` 기본값을 가진다.
- 즐겨찾기 장식 문자열은 표시 전용이며 파일 작업에는 canonical 프로필 이름을 사용한다.

## 변경 체크리스트

이벤트 필드를 추가하거나 바꿀 때 다음 계약을 함께 확인한다.

1. `app/core/models.py`의 모델과 기본값
2. `app/storage/profile_storage.py`의 직렬화·역직렬화 호환성
3. 관련 편집 UI와 복사/import 경로
4. `app/core/processor.py`의 런타임 처리
5. 해당 동작을 검증하는 기존 테스트

설정을 추가하거나 바꿀 때는 `UserSettings`, `app/ui/settings.py`, 설정 저장·복원 테스트를 함께 확인한다.
