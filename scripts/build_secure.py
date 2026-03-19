import argparse
import os
import re
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

VERSION = "3.0"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENTRY_SCRIPT = PROJECT_ROOT / "main_secure.py"
DIST_ROOT = PROJECT_ROOT / "dist" / "secure"
WORK_ROOT = PROJECT_ROOT / "build" / "pyinstaller"
REQUIRED_ENV_VARS = ("AUTH_URL", "VALIDATE_URL")
GETENV_PATTERN = re.compile(r'os\.getenv\(\s*(["\'])([A-Z0-9_]+)\1\s*\)')
HIDDEN_IMPORTS = [
    "app.core.models",
    "app.core.capturer",
    "app.core.processor",
    "app.storage.profile_display",
    "app.storage.profile_storage",
    "app.ui.event_editor",
    "app.ui.event_graph",
    "app.ui.event_importer",
    "app.ui.modkeys",
    "app.ui.profiles",
    "app.ui.quick_event_editor",
    "app.ui.settings",
    "app.ui.simulator_app",
    "app.ui.sort_events",
    "app.utils.i18n",
    "app.utils.runtime_toggle",
    "app.utils.sound_assets",
    "app.utils.sounds",
    "app.utils.system",
]
PLATFORM_NAMES = {
    "darwin": "macos",
    "win32": "windows",
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Build the secure KeystrokeSimulator executable for the current OS."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate build inputs and report output locations without building.",
    )
    return parser.parse_args()


def get_platform_name() -> str:
    platform_name = PLATFORM_NAMES.get(sys.platform)
    if platform_name is None:
        raise SystemExit(f"Unsupported build platform: {sys.platform}")
    return platform_name


def load_required_env() -> dict[str, str]:
    load_dotenv(PROJECT_ROOT / ".env")
    env_values = {name: os.getenv(name, "").strip() for name in REQUIRED_ENV_VARS}
    missing = [name for name, value in env_values.items() if not value]
    if missing:
        joined = ", ".join(missing)
        raise SystemExit(f"Missing required environment variable(s): {joined}")
    return env_values


def render_secure_entry(entry_path: Path, env_values: dict[str, str]) -> str:
    content = entry_path.read_text(encoding="utf-8")

    def replace_env(match: re.Match[str]) -> str:
        env_name = match.group(2)
        value = env_values.get(env_name)
        if value is None:
            return match.group(0)
        return repr(value)

    return GETENV_PATTERN.sub(replace_env, content)


def build_artifact_name(platform_name: str) -> str:
    return f"keystroke_simulator_secure_v{VERSION}_{platform_name}"


def build_output_paths(platform_name: str) -> tuple[Path, Path, Path]:
    dist_dir = DIST_ROOT / platform_name
    work_dir = WORK_ROOT / platform_name
    spec_dir = work_dir / "spec"
    return dist_dir, work_dir, spec_dir


def build(platform_name: str, env_values: dict[str, str]) -> Path:
    import PyInstaller.__main__

    artifact_name = build_artifact_name(platform_name)
    dist_dir, work_dir, spec_dir = build_output_paths(platform_name)
    dist_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    spec_dir.mkdir(parents=True, exist_ok=True)

    secure_entry = render_secure_entry(ENTRY_SCRIPT, env_values)

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".py",
        delete=False,
        dir=work_dir,
        encoding="utf-8",
    ) as temp_file:
        temp_file.write(secure_entry)
        temp_file_path = Path(temp_file.name)

    try:
        os.chdir(PROJECT_ROOT)
        PyInstaller.__main__.run(
            [
                str(temp_file_path),
                "--onefile",
                "--noconsole",
                "--clean",
                "--noconfirm",
                "--noupx",
                f"--name={artifact_name}",
                f"--distpath={dist_dir}",
                f"--workpath={work_dir / 'work'}",
                f"--specpath={spec_dir}",
                f"--paths={PROJECT_ROOT}",
                *[f"--hidden-import={module}" for module in HIDDEN_IMPORTS],
            ]
        )
    finally:
        temp_file_path.unlink(missing_ok=True)

    return dist_dir


def main():
    args = parse_args()
    platform_name = get_platform_name()
    env_values = load_required_env()
    artifact_name = build_artifact_name(platform_name)
    dist_dir, work_dir, spec_dir = build_output_paths(platform_name)

    if args.check:
        print(f"Platform: {platform_name}")
        print(f"Entry script: {ENTRY_SCRIPT}")
        print(f"Artifact name: {artifact_name}")
        print(f"Dist dir: {dist_dir}")
        print(f"Work dir: {work_dir}")
        print(f"Spec dir: {spec_dir}")
        print(f"Embedded env vars: {', '.join(REQUIRED_ENV_VARS)}")
        return

    built_dist_dir = build(platform_name, env_values)
    print(f"Build completed: {built_dist_dir}")


if __name__ == "__main__":
    main()
