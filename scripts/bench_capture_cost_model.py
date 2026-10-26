"""중간 면적 grab 곡선 + 짧은 보정 모델 검증.

작업 계획(이 스크립트가 수행하는 것):
1. 호출 단가 C: 1x1 grab median
2. 면적 곡선 U(A): 정사각/직사각 ROI를 작은 값부터 primary까지
3. 보정 오버헤드: C용 샘플 + U_full용 샘플에 걸리는 시간
4. 정책 시뮬: cost = N*C vs U(union_area) 선택이 실제 per_group/union_crop 승자와 맞는지

실행:
  uv run -m scripts.bench_capture_cost_model
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.engine.processor import ImageFrame
from app.engine.screen_backend import MssScreenBackend, union_group_rects
from app.platform.system import MonitorUtils
from scripts.bench_capture_strategies import (
    _build_groups,
    _timed_samples,
    make_scenarios,
    strategy_per_group,
    strategy_union_crop,
)


@dataclass(frozen=True)
class AreaSample:
    width: int
    height: int
    area: int
    median_ms: float
    p95_ms: float


def _percentile(samples: list[float], p: float) -> float:
    ordered = sorted(samples)
    if len(ordered) == 1:
        return ordered[0]
    idx = min(len(ordered) - 1, max(0, int(round(p * (len(ordered) - 1)))))
    return ordered[idx]


def _grab_rect(sct: Any, left: int, top: int, width: int, height: int) -> None:
    ImageFrame.from_screenshot(
        sct.grab({"left": left, "top": top, "width": width, "height": height})
    )


def measure_call_cost(sct: Any, *, left: int, top: int, iters: int, warmup: int) -> float:
    samples = _timed_samples(
        lambda: _grab_rect(sct, left, top, 1, 1),
        warmup=warmup,
        iters=iters,
    )
    return statistics.median(samples)


def measure_area_curve(
    sct: Any,
    *,
    screen_w: int,
    screen_h: int,
    sizes: list[tuple[int, int]],
    iters: int,
    warmup: int,
) -> list[AreaSample]:
    out: list[AreaSample] = []
    origin_left, origin_top = 8, 8
    for width, height in sizes:
        width = min(width, screen_w - origin_left)
        height = min(height, screen_h - origin_top)
        if width < 1 or height < 1:
            continue
        n_iter = iters
        area = width * height
        if area >= 1_000_000:
            n_iter = min(iters, 20)
        samples = _timed_samples(
            lambda w=width, h=height: _grab_rect(sct, origin_left, origin_top, w, h),
            warmup=min(warmup, max(2, n_iter // 2)),
            iters=n_iter,
        )
        sample = AreaSample(
            width=width,
            height=height,
            area=area,
            median_ms=statistics.median(samples),
            p95_ms=_percentile(samples, 0.95),
        )
        out.append(sample)
        print(
            f"area {width}x{height} ({area}): med={sample.median_ms:.3f}ms "
            f"p95={sample.p95_ms:.3f}ms",
            flush=True,
        )
    return out


def estimate_u(area: int, curve: list[AreaSample], u_full: float) -> float:
    """단조 보간. 곡선 밖은 양 끝/ U_full 상한."""
    if not curve:
        return u_full
    ordered = sorted(curve, key=lambda s: s.area)
    if area <= ordered[0].area:
        return ordered[0].median_ms
    if area >= ordered[-1].area:
        return min(u_full, ordered[-1].median_ms)
    for left, right in zip(ordered, ordered[1:], strict=False):
        if left.area <= area <= right.area:
            if right.area == left.area:
                return left.median_ms
            t = (area - left.area) / (right.area - left.area)
            return left.median_ms + t * (right.median_ms - left.median_ms)
    return u_full


def measure_calibration_overhead(
    sct: Any,
    *,
    screen_w: int,
    screen_h: int,
    call_samples: int,
    full_samples: int,
) -> dict[str, float]:
    t0 = time.perf_counter()
    call_vals = [
        _timed_samples(lambda: _grab_rect(sct, 8, 8, 1, 1), warmup=1, iters=1)[0]
        for _ in range(call_samples)
    ]
    full_vals = [
        _timed_samples(
            lambda: _grab_rect(sct, 0, 0, screen_w, screen_h),
            warmup=0,
            iters=1,
        )[0]
        for _ in range(full_samples)
    ]
    elapsed = (time.perf_counter() - t0) * 1000.0
    return {
        "elapsed_ms": elapsed,
        "C_ms": statistics.median(call_vals),
        "U_full_ms": statistics.median(full_vals),
        "call_samples": float(call_samples),
        "full_samples": float(full_samples),
    }


def simulate_policy(
    sct: Any,
    *,
    screen_w: int,
    screen_h: int,
    c_ms: float,
    curve: list[AreaSample],
    u_full: float,
    counts: list[int],
    iters: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for count in counts:
        for scenario in make_scenarios(screen_w, screen_h, count, seed=42):
            groups = _build_groups(scenario.points)
            n = len(groups)
            union = union_group_rects(groups) if groups else None
            union_area = (
                max(1, union["width"]) * max(1, union["height"]) if union else 0
            )
            pred_group = n * c_ms
            pred_union = estimate_u(union_area, curve, u_full)
            choose_union = pred_union < pred_group

            # 실제 측정은 반복을 줄여 정책 검증용으로만 사용
            n_iter = max(8, min(iters, 24 if n <= 5 else 12))
            if union_area >= 1_000_000:
                n_iter = min(n_iter, 12)
            actual_group = statistics.median(
                _timed_samples(
                    lambda g=groups: strategy_per_group(sct, g),
                    warmup=2,
                    iters=n_iter,
                )
            )
            actual_union = statistics.median(
                _timed_samples(
                    lambda g=groups: strategy_union_crop(sct, g),
                    warmup=2,
                    iters=n_iter,
                )
            )
            actual_best_union = actual_union < actual_group
            row = {
                "scenario": scenario.name,
                "n_events": count,
                "n_groups": n,
                "union_area": union_area,
                "pred_group_ms": round(pred_group, 3),
                "pred_union_ms": round(pred_union, 3),
                "choose_union": choose_union,
                "actual_group_ms": round(actual_group, 3),
                "actual_union_ms": round(actual_union, 3),
                "actual_best_union": actual_best_union,
                "decision_ok": choose_union == actual_best_union,
                "regret_ms": round(
                    abs(
                        (actual_union if choose_union else actual_group)
                        - min(actual_group, actual_union)
                    ),
                    3,
                ),
            }
            rows.append(row)
            print(
                f"policy {scenario.name} n={count} groups={n}: "
                f"pred={'union' if choose_union else 'group'} "
                f"actual={'union' if actual_best_union else 'group'} "
                f"ok={row['decision_ok']} regret={row['regret_ms']}ms",
                flush=True,
            )
    return rows


def default_sizes(screen_w: int, screen_h: int) -> list[tuple[int, int]]:
    # 중간 면적을 촘촘히: 변 길이 기준
    sides = [1, 8, 32, 64, 128, 256, 512, 768, 1024, 1536, 2048]
    sizes = [(s, s) for s in sides if s <= max(screen_w, screen_h)]
    sizes.append((screen_w, screen_h))
    # 와이드 ROI 몇 점
    sizes.extend(
        [
            (screen_w, 64),
            (screen_w, 256),
            (512, screen_h),
            (screen_w // 2, screen_h // 2),
        ]
    )
    # 중복 제거, 면적 순
    uniq: dict[tuple[int, int], None] = {}
    for item in sizes:
        uniq[(min(item[0], screen_w), min(item[1], screen_h))] = None
    return sorted(uniq.keys(), key=lambda wh: wh[0] * wh[1])


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--iters", type=int, default=30)
    p.add_argument("--warmup", type=int, default=4)
    p.add_argument("--counts", default="20,50,100")
    p.add_argument("--policy-iters", type=int, default=16)
    return p.parse_args()


def main() -> int:
    if platform.system() != "Windows":
        raise SystemExit("Windows mss 전용")

    args = parse_args()
    counts = [int(x.strip()) for x in args.counts.split(",") if x.strip()]
    screen_w, screen_h = MonitorUtils.get_primary_size()
    backend = MssScreenBackend()
    backend.open()
    assert backend._sct is not None
    sct = backend._sct

    report: dict[str, Any] = {
        "screen": [screen_w, screen_h],
        "platform": platform.system(),
    }
    try:
        print("== 1) call cost C ==", flush=True)
        c_ms = measure_call_cost(sct, left=8, top=8, iters=args.iters, warmup=args.warmup)
        report["C_ms"] = c_ms
        print(f"C_ms={c_ms:.3f}", flush=True)

        print("== 2) area curve U(A) ==", flush=True)
        curve = measure_area_curve(
            sct,
            screen_w=screen_w,
            screen_h=screen_h,
            sizes=default_sizes(screen_w, screen_h),
            iters=args.iters,
            warmup=args.warmup,
        )
        report["area_curve"] = [asdict(s) for s in curve]
        u_full = next(
            (s.median_ms for s in curve if s.width == screen_w and s.height == screen_h),
            curve[-1].median_ms,
        )
        report["U_full_ms"] = u_full

        print("== 3) calibration overhead ==", flush=True)
        calib = measure_calibration_overhead(
            sct,
            screen_w=screen_w,
            screen_h=screen_h,
            call_samples=5,
            full_samples=2,
        )
        report["calibration"] = calib
        print(
            f"calib elapsed={calib['elapsed_ms']:.1f}ms "
            f"C={calib['C_ms']:.3f} U_full={calib['U_full_ms']:.3f}",
            flush=True,
        )

        # 보정값으로 정책 시뮬 (실사용에 가깝게)
        c_use = calib["C_ms"]
        u_use = calib["U_full_ms"]
        print("== 4) policy simulation ==", flush=True)
        rows = simulate_policy(
            sct,
            screen_w=screen_w,
            screen_h=screen_h,
            c_ms=c_use,
            curve=curve,
            u_full=u_use,
            counts=counts,
            iters=args.policy_iters,
        )
        report["policy_rows"] = rows
        ok = sum(1 for r in rows if r["decision_ok"])
        report["policy_accuracy"] = {
            "ok": ok,
            "total": len(rows),
            "rate": ok / len(rows) if rows else 0.0,
            "mean_regret_ms": statistics.mean(r["regret_ms"] for r in rows) if rows else 0.0,
            "max_regret_ms": max((r["regret_ms"] for r in rows), default=0.0),
        }
        # N*C vs U_full only (곡선 없이 상한만)
        simple_ok = 0
        for r in rows:
            pred_union = u_use < (r["n_groups"] * c_use)
            if pred_union == r["actual_best_union"]:
                simple_ok += 1
        report["simple_Ufull_accuracy"] = {
            "ok": simple_ok,
            "total": len(rows),
            "rate": simple_ok / len(rows) if rows else 0.0,
        }
        # break-even N
        report["break_even_N_vs_Ufull"] = (u_use / c_use) if c_use > 0 else None
    finally:
        backend.close()

    out = Path(__file__).resolve().parent / "bench_capture_cost_model_last.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    txt = Path(__file__).resolve().parent / "bench_capture_cost_model_last.txt"
    lines = [
        f"screen={screen_w}x{screen_h}",
        f"C_ms={report['C_ms']:.3f}",
        f"U_full_ms={report['U_full_ms']:.3f}",
        f"break_even_N={report['break_even_N_vs_Ufull']:.2f}",
        f"calib_ms={report['calibration']['elapsed_ms']:.1f}",
        f"policy_curve_acc={report['policy_accuracy']['rate']:.3f} "
        f"regret_mean={report['policy_accuracy']['mean_regret_ms']:.3f} "
        f"regret_max={report['policy_accuracy']['max_regret_ms']:.3f}",
        f"policy_Ufull_acc={report['simple_Ufull_accuracy']['rate']:.3f}",
        "",
        "area_curve:",
    ]
    for s in report["area_curve"]:
        lines.append(
            f"  {s['width']}x{s['height']} area={s['area']} "
            f"med={s['median_ms']:.3f} p95={s['p95_ms']:.3f}"
        )
    lines.append("")
    lines.append("policy_rows:")
    for r in report["policy_rows"]:
        lines.append(
            f"  {r['scenario']} n={r['n_events']} g={r['n_groups']} "
            f"pred={'U' if r['choose_union'] else 'G'} "
            f"act={'U' if r['actual_best_union'] else 'G'} "
            f"ok={r['decision_ok']} regret={r['regret_ms']}"
        )
    txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"wrote {out}")
    print(f"wrote {txt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
