"""Windows 캡처 호출·그룹화 전략 실측.

키 hold / loop delay 는 측정하지 않는다. grab 형태와 그룹화만 비교한다.

전략:
  per_group   — 현재 실행 루프 (그룹마다 mss.grab)
  per_pixel   — 그룹화 없이 픽셀마다 1x1 grab
  union_crop  — 전 그룹 외접 1회 grab 후 메모리 crop (Mac식에 가까운 Windows 대안)

시나리오:
  clustered   — 한 덩어리로 몰린 픽셀
  dual_cluster— 멀리 떨어진 두 덩어리
  dispersed   — 화면을 격자처럼 고르게 분산
  random      — primary 안 균등 난수

실행:
  uv run -m scripts.bench_capture_strategies
  uv run -m scripts.bench_capture_strategies --iters 80 --counts 20,50,100
"""

from __future__ import annotations

import argparse
import platform
import random
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.processor import CaptureGroup, EventData, ImageFrame, KeystrokeProcessor
from app.core.screen_backend import MssScreenBackend, union_group_rects
from app.utils.system import MonitorUtils
from tests.helpers import make_processor_stub


@dataclass(frozen=True)
class Scenario:
    name: str
    points: list[tuple[int, int]]


@dataclass(frozen=True)
class StrategyResult:
    strategy: str
    scenario: str
    event_count: int
    group_count: int
    sum_group_area: int
    union_area: int
    samples_ms: list[float]

    @property
    def median_ms(self) -> float:
        return statistics.median(self.samples_ms)

    @property
    def p95_ms(self) -> float:
        if len(self.samples_ms) == 1:
            return self.samples_ms[0]
        ordered = sorted(self.samples_ms)
        idx = min(len(ordered) - 1, max(0, int(round(0.95 * (len(ordered) - 1)))))
        return ordered[idx]


def _pixel_event(name: str, x: int, y: int) -> EventData:
    return {
        "name": name,
        "mode": "pixel",
        "invert": False,
        "key": "A",
        "center_x": x,
        "center_y": y,
        "dur": None,
        "rand": None,
        "exec": True,
        "group": None,
        "priority": 0,
        "conds": {},
        "runtime_toggle_member": False,
        "region_w": 1,
        "region_h": 1,
        "rel_x": 0,
        "rel_y": 0,
        "ref_bgr": (0, 0, 0),
    }


def _build_groups(points: list[tuple[int, int]]) -> list[CaptureGroup]:
    proc = make_processor_stub()
    # Windows 경로: clamp 없음. 측정은 실제 OS 분기를 그대로 쓴다.
    proc.os_type = platform.system()
    events = [_pixel_event(f"p{i}", x, y) for i, (x, y) in enumerate(points)]
    return KeystrokeProcessor._build_capture_groups(proc, events)


def _rect_area(rect: dict[str, int]) -> int:
    return max(1, rect["width"]) * max(1, rect["height"])


def _crop_frame(frame: ImageFrame, rect: dict[str, int], origin: dict[str, int]) -> ImageFrame:
    x = rect["left"] - origin["left"]
    y = rect["top"] - origin["top"]
    return frame.crop(x, y, rect["width"], rect["height"])


def _read_pixels(frame: ImageFrame, count: int) -> None:
    # 매칭 비용을 아주 약하게 포함 (픽셀 모드 1회 읽기 근사)
    w, h = frame.width, frame.height
    for i in range(count):
        frame.pixel_bgr(min(w - 1, i % w), min(h - 1, (i * 3) % h))


def _timed_samples(fn: Any, *, warmup: int, iters: int) -> list[float]:
    for _ in range(warmup):
        fn()
    samples: list[float] = []
    for _ in range(iters):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    return samples


def strategy_per_group(sct: Any, groups: list[CaptureGroup]) -> None:
    frames = [ImageFrame.from_screenshot(sct.grab(g["rect"])) for g in groups]
    for group, frame in zip(groups, frames, strict=True):
        _read_pixels(frame, max(1, len(group["events"])))


def strategy_per_pixel(sct: Any, points: list[tuple[int, int]]) -> None:
    for x, y in points:
        frame = ImageFrame.from_screenshot(
            sct.grab({"left": x, "top": y, "width": 1, "height": 1})
        )
        _read_pixels(frame, 1)


def strategy_union_crop(sct: Any, groups: list[CaptureGroup]) -> None:
    if not groups:
        return
    union = union_group_rects(groups)
    big = ImageFrame.from_screenshot(sct.grab(union))
    for group in groups:
        cropped = _crop_frame(big, group["rect"], union)
        _read_pixels(cropped, max(1, len(group["events"])))


def make_scenarios(screen_w: int, screen_h: int, count: int, seed: int) -> list[Scenario]:
    rng = random.Random(seed + count)
    margin = 8
    usable_w = max(1, screen_w - 2 * margin)
    usable_h = max(1, screen_h - 2 * margin)

    # 몰림: 좌상단 근처 작은 격자
    cluster_origin = (margin + 40, margin + 40)
    clustered: list[tuple[int, int]] = []
    cols = max(1, int(count**0.5))
    for i in range(count):
        clustered.append(
            (
                cluster_origin[0] + (i % cols) * 3,
                cluster_origin[1] + (i // cols) * 3,
            )
        )

    # 두 덩어리: 좌상 / 우하
    half = count // 2
    dual: list[tuple[int, int]] = []
    for i in range(half):
        dual.append((margin + 20 + (i % 8) * 3, margin + 20 + (i // 8) * 3))
    for i in range(count - half):
        dual.append(
            (
                screen_w - margin - 60 + (i % 8) * 3,
                screen_h - margin - 60 + (i // 8) * 3,
            )
        )

    # 고른 분산: 격자
    dispersed: list[tuple[int, int]] = []
    grid = max(1, int(count**0.5))
    for i in range(count):
        gx = i % grid
        gy = i // grid
        dispersed.append(
            (
                margin + int((gx + 0.5) * usable_w / grid),
                margin + int((gy + 0.5) * usable_h / max(1, (count + grid - 1) // grid)),
            )
        )

    # 완전 난수
    randomized = [
        (
            margin + rng.randrange(usable_w),
            margin + rng.randrange(usable_h),
        )
        for _ in range(count)
    ]

    return [
        Scenario("clustered", clustered),
        Scenario("dual_cluster", dual),
        Scenario("dispersed", dispersed),
        Scenario("random", randomized),
    ]


def _iters_for(strategy: str, event_count: int, union_area: int, base_iters: int) -> int:
    """비싼 조합은 반복을 줄여 전체 벤치 시간을 제한한다."""
    if strategy == "per_pixel":
        return max(8, min(base_iters, 400 // max(1, event_count)))
    if strategy == "union_crop" and union_area >= 1_000_000:
        return max(8, min(base_iters, 20))
    return base_iters


def run_benchmark(
    *,
    counts: list[int],
    iters: int,
    warmup: int,
    seed: int,
) -> list[StrategyResult]:
    if platform.system() != "Windows":
        raise SystemExit("이 벤치는 Windows mss 경로 전용입니다.")

    screen_w, screen_h = MonitorUtils.get_primary_size()
    backend = MssScreenBackend()
    backend.open()
    assert backend._sct is not None
    sct = backend._sct

    results: list[StrategyResult] = []
    try:
        for count in counts:
            for scenario in make_scenarios(screen_w, screen_h, count, seed):
                groups = _build_groups(scenario.points)
                sum_area = sum(_rect_area(g["rect"]) for g in groups)
                union_area = _rect_area(union_group_rects(groups)) if groups else 0
                print(
                    f"measuring {scenario.name} n={count} groups={len(groups)} "
                    f"sum_a={sum_area} union_a={union_area}",
                    flush=True,
                )

                for strategy, runner, group_count, reported_sum in (
                    (
                        "per_group",
                        lambda g=groups: strategy_per_group(sct, g),
                        len(groups),
                        sum_area,
                    ),
                    (
                        "per_pixel",
                        lambda pts=scenario.points: strategy_per_pixel(sct, pts),
                        count,
                        count,
                    ),
                    (
                        "union_crop",
                        lambda g=groups: strategy_union_crop(sct, g),
                        len(groups),
                        sum_area,
                    ),
                ):
                    n_iter = _iters_for(strategy, count, union_area, iters)
                    n_warm = min(warmup, max(2, n_iter // 2))
                    print(f"  -> {strategy} iters={n_iter}", flush=True)
                    samples = _timed_samples(runner, warmup=n_warm, iters=n_iter)
                    results.append(
                        StrategyResult(
                            strategy=strategy,
                            scenario=scenario.name,
                            event_count=count,
                            group_count=group_count,
                            sum_group_area=reported_sum,
                            union_area=union_area,
                            samples_ms=samples,
                        )
                    )
    finally:
        backend.close()

    return results


def _print_report(results: list[StrategyResult], screen: tuple[int, int]) -> None:
    lines: list[str] = []
    lines.append(f"screen={screen[0]}x{screen[1]}  platform={platform.system()}")
    lines.append(
        f"{'scenario':<13} {'n':>4} {'strat':<10} {'groups':>6} "
        f"{'sum_a':>8} {'union_a':>8} {'med_ms':>8} {'p95_ms':>8} {'vs_group':>9}"
    )
    lines.append("-" * 90)

    baseline: dict[tuple[str, int], float] = {}
    for row in results:
        if row.strategy == "per_group":
            baseline[(row.scenario, row.event_count)] = row.median_ms

    for row in results:
        base = baseline.get((row.scenario, row.event_count), row.median_ms)
        ratio = row.median_ms / base if base > 0 else 0.0
        lines.append(
            f"{row.scenario:<13} {row.event_count:>4} {row.strategy:<10} "
            f"{row.group_count:>6} {row.sum_group_area:>8} {row.union_area:>8} "
            f"{row.median_ms:>8.3f} {row.p95_ms:>8.3f} {ratio:>8.2f}x"
        )

    lines.append("")
    lines.append("guide:")
    lines.append("- per_group = current app path (baseline vs_group=1.00x)")
    lines.append("- vs_group < 1 means faster than current")
    lines.append(
        "- when union_area >> sum_group_area and groups is small, per_group usually wins"
    )
    lines.append(
        "- when groups is large, union_crop usually wins (mss call overhead dominates)"
    )

    winners: dict[tuple[str, int], StrategyResult] = {}
    for row in results:
        key = (row.scenario, row.event_count)
        prev = winners.get(key)
        if prev is None or row.median_ms < prev.median_ms:
            winners[key] = row
    lines.append("")
    lines.append("fastest per scenario:")
    for (scenario, count), row in sorted(winners.items(), key=lambda item: (item[0][0], item[0][1])):
        lines.append(
            f"- {scenario} n={count}: {row.strategy} "
            f"{row.median_ms:.3f}ms (groups={row.group_count}, union_a={row.union_area})"
        )

    text = "\n".join(lines) + "\n"
    print(text, end="")
    out = Path(__file__).resolve().parent / "bench_capture_strategies_last.txt"
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--counts",
        default="20,50,100",
        help="픽셀 이벤트 개수 목록 (쉼표 구분)",
    )
    parser.add_argument("--iters", type=int, default=60, help="반복 횟수")
    parser.add_argument("--warmup", type=int, default=8, help="워밍업 횟수")
    parser.add_argument("--seed", type=int, default=42, help="난수 시드")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    counts = [int(part.strip()) for part in args.counts.split(",") if part.strip()]
    screen = MonitorUtils.get_primary_size()
    results = run_benchmark(
        counts=counts,
        iters=args.iters,
        warmup=args.warmup,
        seed=args.seed,
    )
    _print_report(results, screen)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
