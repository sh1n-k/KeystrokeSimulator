import os
import tempfile

from dotenv import load_dotenv, find_dotenv

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

    # Create a temporary file
    temp_file = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False)
    temp_file.write(content)
    temp_file.close()

    return temp_file.name


if __name__ == "__main__":
    # Create a temporary script with replaced environment variables
    temp_main = create_temp_script("main_secure.py")

    import PyInstaller.__main__

    PyInstaller.__main__.run(
        [
            temp_main,
            "--onefile",
            "--windowed",
            "--noconfirm",
            "--log-level=WARN",
            "--onefile",
            "--nowindow",
            "--optimize=2",
            "--strip",
        ]
    )
