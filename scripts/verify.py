import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

STATIC_CHECKS = (
    ("ruff", (sys.executable, "-m", "ruff", "check", ".")),
    ("pyright", (sys.executable, "-m", "pyright")),
)
TEST_CHECKS = (
    (
        "unittest",
        (
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests",
            "-p",
            "test_*.py",
            "-q",
        ),
    ),
)


def run_checks(checks: tuple[tuple[str, tuple[str, ...]], ...]) -> int:
    for name, command in checks:
        print(f"==> {name}", flush=True)
        result = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
        if result.returncode != 0:
            return result.returncode
    return 0


def run_static_checks() -> int:
    return run_checks(STATIC_CHECKS)


def run_all_checks() -> int:
    return run_checks(STATIC_CHECKS + TEST_CHECKS)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run KeystrokeSimulator validation checks."
    )
    parser.add_argument(
        "--static-only",
        action="store_true",
        help="Run ruff and pyright without the unittest suite.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.static_only:
        return run_static_checks()
    return run_all_checks()


if __name__ == "__main__":
    raise SystemExit(main())
