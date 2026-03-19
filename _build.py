import os
import tempfile

import PyInstaller.__main__
from dotenv import load_dotenv, find_dotenv

from app.compat.legacy import canonical_module_names, legacy_module_names

VERSION = "3.0"
PROJECT_ROOT = os.path.dirname(__file__)
HIDDEN_IMPORTS = canonical_module_names() + legacy_module_names()

# Load environment variables
load_dotenv(find_dotenv())


# Function to create a temporary script with replaced environment variables
def create_temp_script(filename):
    with open(filename, "r", encoding="utf-8") as file:
        content = file.read()

    # Replace environment variable references with actual values
    for key, value in os.environ.items():
        content = content.replace(f"os.getenv('{key}')", f"'{value}'")
        content = content.replace(f'os.getenv("{key}")', f"'{value}'")

    return content


if __name__ == "__main__":
    # Read the original script and replace environment variables
    script_content = create_temp_script("main_secure.py")

    # Create a temporary file using NamedTemporaryFile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as temp_file:
        temp_file.write(script_content)
        temp_file_path = temp_file.name

    try:
        # Run PyInstaller with the temporary script
        PyInstaller.__main__.run(
            [
                temp_file_path,
                "--onefile",
                "--noconsole",
                "--clean",
                "--noupx",
                f"--name=main_secure_v{VERSION}",
                f"--paths={PROJECT_ROOT}",
                *[f"--hidden-import={module}" for module in HIDDEN_IMPORTS],
            ]
        )
    finally:
        # Clean up the temporary file
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
