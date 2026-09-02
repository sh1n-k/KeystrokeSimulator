# Windows 적응형 캡처 개선안

상태: 실측 기반 설계안 (**구현됨** — `MssScreenBackend` 적응형 grab)  
대상: Windows `MssScreenBackend` 실행 루프 grab  
비대상: 키 hold, loop delay, DXGI/mss 제거, macOS SCStream

## 1. 문제

프로필 픽셀 배치는 사용 환경에 따라 몰림·분산이 섞인다. 현재는 항상 **그룹마다 `mss.grab`** 이라서:

- 몰림/소그룹: 양호 (~7–14ms)
- 다수 그룹 분산: 호출 수에 비례해 100~500ms+로 폭주

키 타이밍은 유지한 채, **캡처 최악 지연만 안정화**하는 것이 목표다.

## 2. 측정으로 확정된 사실

환경: Windows, primary 2560×1440.  
스크립트: `scripts/bench_capture_strategies.py`, `scripts/bench_capture_cost_model.py`  
산출: `scripts/bench_capture_*_last.txt`, `scripts/bench_capture_cost_model_last.json`

| 관측 | 수치 |
|------|------|
| 호출 단가 C (1×1 등 소형) | ≈ **6.8–7.2ms**, ~512² / 가로 full×256까지 거의 평탄 |
| 중간 면적 | ~0.7–1.0M px에서 ≈ **13–14ms** 로 계단 |
| primary 전체 U_full | ≈ **28–38ms** (런 간 분산 있음) |
| 손익분기 (U_full / C) | ≈ **5.4회** |
| 기동 보정(5×1x1 + 2×full) | ≈ **144ms** 1회 |

정책 시뮬 (합성 clustered/dual/dispersed/random × n=20/50/100):

| 모델 | 정확도 | 비고 |
|------|--------|------|
| `N*C` vs 곡선보간 `U(A)` | 75% (9/12) | 실패는 전부 **N=1**; regret ≤ 0.7ms |
| `N*C` vs `U_full`(보정값) | **12/12** | **이 합성 세트 한정**. N=3~6·실프로필은 미검증 |

해석: 중간 면적 곡선은 “면적이 커질수록 비싸진다”를 보여 주지만, **선택 로직의 1차 판정에는 `U_full` 상한으로 충분**하고 더 안전하다. N=1은 비교 없이 그룹 경로를 쓰면 곡선 오판이 사라진다.

**수치 출처를 섞지 말 것:** 같은 실행에서도 곡선상의 full median(≈28ms)과 보정용 full×2 median(≈38ms)이 달랐다. 판정에는 **보정으로 얻은 `C`/`U_full`만** 쓴다. break-even `U_full/C`는 보정 기준 ≈5.4이며, 곡선 full로 나누면 ≈4.0이 된다. 고정 상수 `N>=5`와 실무 문턱이 비슷해 보여도, 기기 변동을 흡수하려면 보정값을 쓰는 편이 낫다.

## 3. 채택 판정 로직

### 3.1 런타임 보정 (다그룹 grab 시 1회, lazy)

```text
C      = median(1×1 grab × 3~5)
U_full = median(primary 전체 grab × 1~2)
# 실패·이상치면 비용 unset → 이후 per_group degrade
```

- 트리거: **`grab(groups)`에서 `len(groups) > 1`이고 아직 보정 시도가 없을 때 1회**.
- 미리보기(`capturer`)는 보통 N=1이라 **보정·지연(~150ms)을 내지 않는다**.
- 매 사이클 보정 금지. 실패 후에도 재시도하지 않고 per_group 유지.
- `U_full`은 p50보다 **약간 보수적으로**(예: max(median, p95*0.9) 또는 +10%) 잡아도 된다. 그러면 애매한 구간에서 per_group을 선호.

### 3.2 매 사이클(또는 그룹 재구축 시) 선택

`groups = main_capture_groups`, `N = len(groups)`.

```text
if N <= 1:
    strategy = per_group
elif N * C > U_full * 1.05:  # 동률·근접 구간(≤1.05)은 per_group
    strategy = union_crop   # 외접 1회 grab 후 그룹 rect crop
else:
    strategy = per_group
```

동률·근접: `N * C <= U_full * 1.05` 이면 **per_group** (애매한 break-even 대역 N≈4–6에서 거대 외접 회귀를 피함).  
`union_crop` 예상비에는 crop CPU를 넣지 않는다(실측상 grab 대비 무시 가능). 다만 구현 후 등가 테스트로 확인한다.

### 3.3 `union_crop` 의미

1. `union = union_group_rects(groups)`
2. `big = mss.grab(union)` 1회
3. 각 group에 대해  
   `crop(left - union.left, top - union.top, width, height)`  
   → 기존과 같이 그룹 로컬 `rel_*`로 `_evaluate_capture_group`
4. grab/crop 실패 시 해당 사이클 프레임을 `None`으로 돌려 지금과 같이 사이클 스킵

픽셀 경로·색 공간은 기존 mss와 동일해야 한다 (편집기/실행 일치 유지).

### 3.4 적용 범위 / 비적용

- **적용:** 실행 루프가 여는 `MssScreenBackend` (보통 그룹 N≥1의 `main_capture_groups`)
- **변경 금지:** `ScreenshotCapturer` 미리보기. 미리보기는 이미 박스 1개 grab(N=1)이라 전략이 no-op이며, 실행과 **같은 백엔드 클래스**만 쓰면 기준색 경로가 유지된다. capturer API·fps·full-screen open 계약을 바꾸지 않는다.

### 3.5 채택하지 않는 대안

| 대안 | 이유 |
|------|------|
| 항상 union_crop | dual_cluster(N=2, 거대 외접)에서 ~2.5× 회귀 |
| 고정 `N >= 5`만 | 기기별 C/U 변동에 취약. 보정 대비 이득 없음 |
| DXGI 교체 | 호출 횟수 문제와 무관, 색/복잡도 리스크 |
| `union/sum` 면적비만 | N=2 거대 외접을 오판하기 쉬움 |
| 곡선 보간을 1차 판정에 사용 | 본 측정에서 U_full보다 정확도 낮음; 복잡도 대비 이득 없음 |

곡선 데이터는 **문서·디버그·추후 U(A) 정교화**용으로만 남긴다.

## 4. 구현 경계

- canonical: `app/core/screen_backend.py` (`MssScreenBackend.grab` 또는 동일 레이어 helper)
- 보정 트리거: **다그룹 `grab` 시 lazy 1회** (`open()`이 아님 — 미리보기 N=1 기동 비용 방지).
- 호출부: `processor._capture_match_states`는 가능하면 그대로 두고 백엔드가 전략을 숨김
- Darwin/`MacStreamBackend` 변경 없음
- 키 입력·`delays`·Mod 폴링 변경 없음
- `app/core/capturer.py` 변경 없음
- 테스트:
  - 전략 선택 단위 테스트(가짜 C/U, N=1/2/10)
  - **동일 groups에 대해 per_group vs union_crop 픽셀 등가**(mock 버퍼 또는 고정 화면)
  - grab 호출 횟수 mock (N회 vs 1회)
  - 보정 실패 시 per_group degrade
  - 미리보기 경로(N=1) 회귀 없음
  - 기존 screen_backend Windows 테스트 유지

## 5. 검증 기준

1. 합성 벤치에서 dual_cluster는 per_group, dispersed/random(다수 그룹)은 union
2. clustered(N=1)는 항상 per_group, 매칭 결과 불변
3. 보정 실패 시 per_group degrade
4. break-even 근처(N≈4–6)에서 5% margin으로 불필요한 거대 union을 피하는 mid-size 합성 케이스 1개 이상
5. `uv run -m scripts.verify` 통과
6. (권장) 분산형 실프로필 1개에서 캡처가 loop delay를 상시 잠식하지 않음

## 6. 잔여 리스크

- 보정 구간 U_full 노이즈(같은 런 28 vs 38ms): 보정값·5% margin으로 완화
- break-even 대역(N≈4–6)·대형 단일 그룹(면적은 큰데 N=1): N=1은 항상 per_group이라 호출은 1회이나, 거대 ROI 1회 비용은 그대로 — 별도 이슈
- 멀티 모니터: primary만 보정하면 union이 다른 모니터를 넓게 덮을 때 U_full이 낙관적일 수 있음 → 잔여. 필요 시 실제 union 면적 샘플로 확장
- 해상도/DPI 변경 후 재보정 없음: 프로세스 재시작(open 재호출)에 의존
- 실프로필 분포·N=3~6 실측 부족: 최악 상한 목적은 유효, 평균 이득은 배치 의존

## 7. 결론

**개선 진행을 권고한다.**  
판정 기준은 **다그룹 grab 시 측정한 `C`/`U_full`에 대해 `N≥2` 이고 `N*C > U_full×1.05`이면 외접 1회+crop, 아니면 그룹별 grab** 이다.
중간 면적 측정은 면적 계단을 확인했고, 1차 판정식을 `U(A)` 보간으로 복잡화할 필요는 없음을 보였다.  
“100% 정확”은 **12개 합성 시나리오 + 보정 U_full**에 한정된 결과로만 인용한다.
