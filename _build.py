import os
import tempfile

import PyInstaller.__main__
from dotenv import load_dotenv, find_dotenv

VERSION = "2.0"

# Load environment variables
load_dotenv(find_dotenv())


# Function to create a temporary script with replaced environment variables
def create_temp_script(filename):
    with open(filename, "r") as file:
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
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as temp_file:
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
            ]
        )
    finally:
        # Clean up the temporary file
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
