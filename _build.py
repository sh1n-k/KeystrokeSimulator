import os
import tempfile
import sys
import platform
from dotenv import load_dotenv, find_dotenv
import PyInstaller.__main__

VERSION = "1.3"

# Load environment variables
load_dotenv(find_dotenv())

def check_required_env_vars():
    required_vars = ["AUTH_URL", "VALIDATE_URL"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        print(f"Error: The following required environment variables are missing: {', '.join(missing_vars)}")
        sys.exit(1)

def create_temp_script(filename):
    with open(filename, "r") as file:
        content = file.read()

    for key, value in os.environ.items():
        content = content.replace(f"os.getenv('{key}')", f"'{value}'")
        content = content.replace(f'os.getenv("{key}")', f"'{value}'")

    return content

def get_platform_specific_options():
    system = platform.system().lower()
    machine = platform.machine().lower()

    options = [
        "--onefile",
        "--clean",
        "--optimize=2",
    ]

    if system == "windows":
        options.append("--noconsole")
    elif system == "darwin":
        options.append("--windowed")

    # Add architecture-specific options if needed
    if "arm" in machine:
        options.append("--target-arch=arm64")

    return options

if __name__ == "__main__":
    check_required_env_vars()

    script_content = create_temp_script("main_secure_new.py")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as temp_file:
        temp_file.write(script_content)
        temp_file_path = temp_file.name

    try:
        platform_options = get_platform_specific_options()
        PyInstaller.__main__.run(
            [
                temp_file_path,
                f"--name=main_secure_v{VERSION}",
            ] + platform_options
        )
    finally:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)

print(f"Build completed for {platform.system()} on {platform.machine()}")