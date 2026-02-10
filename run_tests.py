#!/usr/bin/env python3
import argparse
import platform
import subprocess
import sys
from pathlib import Path


def _default_python(project_root: Path) -> str:
    candidates = []
    if platform.system() == "Windows":
        candidates.extend(
            [
                project_root / ".venv" / "Scripts" / "python.exe",
                project_root / ".venv" / "Scripts" / "python",
            ]
        )
    else:
        candidates.append(project_root / ".venv" / "bin" / "python")

    for path in candidates:
        if path.exists():
            return str(path)
    return sys.executable


def main() -> int:
    project_root = Path(__file__).resolve().parent

    parser = argparse.ArgumentParser(
        description="Run unit tests for KeystrokeSimulator (macOS/Windows compatible)."
    )
    parser.add_argument(
        "--python",
        help="Python executable path to run tests with. Default: project .venv or current interpreter.",
    )
    parser.add_argument(
        "--start-dir",
        default="tests",
        help="unittest discover start directory (default: tests)",
    )
    parser.add_argument(
        "--pattern",
        default="test_*.py",
        help="unittest discover pattern (default: test_*.py)",
    )
    parser.add_argument(
        "--top-level-dir",
        default=None,
        help="unittest discover top-level directory (optional)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Run without -v option.",
    )
    args, passthrough = parser.parse_known_args()

    python_exec = args.python or _default_python(project_root)
    cmd = [
        python_exec,
        "-m",
        "unittest",
        "discover",
        "-s",
        args.start_dir,
        "-p",
        args.pattern,
    ]
    if args.top_level_dir:
        cmd.extend(["-t", args.top_level_dir])
    if not args.quiet:
        cmd.append("-v")
    cmd.extend(passthrough)

    print(f"[run_tests] OS: {platform.system()}")
    print(f"[run_tests] Python: {python_exec}")
    print(f"[run_tests] Command: {' '.join(cmd)}")

    proc = subprocess.run(cmd, cwd=project_root)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
