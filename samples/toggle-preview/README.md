# 토글 알림음 미리듣기 샘플 (3세트)

시작/종료 팩과 같은 음색 계열, 더 짧고 음정 구간이 다름.
피크는 약 75% FS. **켜짐 = 짧은 상승, 꺼짐 = 낮은 하강.**

| 세트 | 켜짐 | 꺼짐 | 성격 |
| --- | --- | --- | --- |
| **A** | `setA_on.wav` | `setA_off.wav` | 차임 E5→G5 / G4 |
| **B** | `setB_on.wav` | `setB_off.wav` | 최소 B4→E5 / E4 |
| **C** | `setC_on.wav` | `setC_off.wav` | 화음 C–E→G–B / G–B |

미리듣기:
```bash
afplay samples/toggle-preview/setB_on.wav
afplay samples/toggle-preview/setB_off.wav
```
