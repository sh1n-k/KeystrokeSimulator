# 알림음 미리듣기 샘플 (3세트)

모두 부드러운 sine 기반, 짧은 길이.
피크는 약 75% FS로 맞춰 같은 시스템 볼륨에서 클래식과 비슷한 크기로 들리도록 했습니다.
**시작 = 상승, 종료 = 하강**으로 방향성을 맞췄습니다.

| 세트 | 시작 | 종료 | 성격 |
| --- | --- | --- | --- |
| **A** | `setA_start.wav` | `setA_stop.wav` | 두 음 차임 A4→C5 / C5→A4 |
| **B** | `setB_start.wav` | `setB_stop.wav` | 최소 두 음 E4→B4 / B4→E4 (절제) |
| **C** | `setC_start.wav` | `setC_stop.wav` | 화음 쌍 상승 C–E→G–B / 하강 G–B→C–E |

미리듣기:
```bash
afplay samples/notification-preview/setB_start.wav
afplay samples/notification-preview/setB_stop.wav
afplay samples/notification-preview/setC_start.wav
afplay samples/notification-preview/setC_stop.wav
```
