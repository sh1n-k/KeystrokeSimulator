# 알림음 미리듣기 샘플 (3세트)

모두 부드러운 sine 기반, 짧은 길이.
피크는 약 75% FS로 맞춰 같은 시스템 볼륨에서 클래식과 비슷한 크기로 들리도록 했습니다.
**시작 = 상승, 종료 = 하강**으로 방향성을 맞췄습니다.
첫 음은 자르지 않고 다음 음 아래에서 계속 잦아들게 해 음 사이에 무음 구간이 없습니다.

| 세트 | 시작 | 종료 | 성격 |
| --- | --- | --- | --- |
| **A** | `setA_start.wav` | `setA_stop.wav` | 두 음 차임 A4→C5 / C5→A4 |
| **B** | `setB_start.wav` | `setB_stop.wav` | 최소 두 음 E4→C5 / C5→E4 (절제) |
| **C** | `setC_start.wav` | `setC_stop.wav` | 화음 쌍 상승 C–E→G–B / 하강 G–B→C–E |

미리듣기:
```bash
afplay samples/notification-preview/setB_start.wav
afplay samples/notification-preview/setB_stop.wav
afplay samples/notification-preview/setC_start.wav
afplay samples/notification-preview/setC_stop.wav
```

다시 생성(WAV와 앱에 내장된 시작·종료·토글 ON 음원을 함께 갱신):
```bash
uv run -m scripts.generate_soft_notification_sounds
```
