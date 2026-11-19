import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

STATIC_CHECKS = (
    ("ruff", (sys.executable, "-m", "ruff", "check", ".")),
    ("pyright", (sys.executable, "-m", "pyright")),
)
UNITTEST_COMMAND = (
    sys.executable,
    "-m",
    "unittest",
    "discover",
    "-s",
    str(PROJECT_ROOT / "tests"),
    "-t",
    str(PROJECT_ROOT),
    "-p",
    "test_*.py",
    "-q",
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


def _unittest_env() -> dict[str, str]:
    env = dict(os.environ)
    python_path = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        f"{PROJECT_ROOT}{os.pathsep}{python_path}" if python_path else str(PROJECT_ROOT)
    )
    # 앱 로그(loguru)와 offscreen Qt 플러그인 경고("does not support raise()" 등)는
    # 테스트 출력에서 노이즈다. 필요하면 LOGURU_LEVEL=DEBUG, QT_LOGGING_RULES=로 켠다.
    env.setdefault("LOGURU_LEVEL", "CRITICAL")
    env.setdefault("QT_LOGGING_RULES", "default.warning=false;qt.qpa.*=false")
    return env


def run_unittests() -> int:
    """앱의 상대경로 저장 파일이 저장소 루트를 덮어쓰지 않도록 빈 임시 폴더에서 돌린다.

    테스트가 끝난 뒤 그 폴더에 파일이 남아 있으면 격리 누수로 보고 실패한다.
    """
    print("==> unittest", flush=True)
    with tempfile.TemporaryDirectory(prefix="keystroke-tests-") as sandbox:
        result = subprocess.run(
            UNITTEST_COMMAND, cwd=sandbox, env=_unittest_env(), check=False
        )
        if result.returncode != 0:
            return result.returncode
        leaked = sorted(path.name for path in Path(sandbox).iterdir())
    if leaked:
        print(
            "Tests wrote files into the working directory instead of a temp dir: "
            + ", ".join(leaked),
            flush=True,
        )
        return 1
    return 0


def run_all_checks() -> int:
    code = run_static_checks()
    if code != 0:
        return code
    return run_unittests()


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
