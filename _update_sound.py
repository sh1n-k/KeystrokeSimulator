import sys
import os
import base64
import re


def update_sound_variable(sound_type: str, new_sound_path: str):
    """
    Updates the START_SOUND or STOP_SOUND variable in keystroke_sounds.py
    with a new base64-encoded sound file.

    Args:
        sound_type (str): The type of sound to update ('start' or 'stop').
        new_sound_path (str): The path to the new sound file.
    """
    # 1. Validate inputs
    if sound_type.lower() not in ["start", "stop"]:
        print("Error: Invalid sound type. Please use 'start' or 'stop'.")
        return

    if not os.path.exists(new_sound_path):
        print(f"Error: File not found at '{new_sound_path}'")
        return

    supported_extensions = (".mp3", ".wav", ".ogg")
    if not new_sound_path.lower().endswith(supported_extensions):
        print(
            f"Error: Unsupported file type. Please use one of {supported_extensions}."
        )
        return

    target_file = os.path.join(os.path.dirname(__file__), "keystroke_sounds.py")
    if not os.path.exists(target_file):
        print(f"Error: Target file '{target_file}' not found.")
        return

    # 2. Encode the new sound file
    try:
        with open(new_sound_path, "rb") as f:
            new_sound_base64 = base64.b64encode(f.read()).decode("utf-8")
        print(f"Successfully encoded '{os.path.basename(new_sound_path)}'.")
    except Exception as e:
        print(f"Error encoding file: {e}")
        return

    # 3. Read the target script and update the variable
    try:
        with open(target_file, "r", encoding="utf-8") as f:
            content = f.read()

        variable_name = "START_SOUND" if sound_type.lower() == "start" else "STOP_SOUND"

        # Regex to find the variable assignment and replace its value
        # It looks for `VARIABLE_NAME = "..."` and replaces the content inside the quotes.
        pattern = re.compile(f'^({variable_name} = ").*(")', re.MULTILINE)

        if not pattern.search(content):
            print(
                f"Error: Could not find the '{variable_name}' variable in '{target_file}'."
            )
            return

        updated_content = pattern.sub(f"\\g<1>{new_sound_base64}\\g<2>", content)

        # 4. Write the updated content back to the file
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(updated_content)

        print(f"Successfully updated the '{variable_name}' in '{target_file}'.")

    except Exception as e:
        print(f"An error occurred while updating the file: {e}")


def main():
    """Main function to handle command-line arguments."""
    if len(sys.argv) != 3:
        print("Usage: python _update_sound.py <start|stop> <path_to_sound_file>")
        print(
            'Example: python _update_sound.py start "C:\\Users\\Me\\sounds\\new_start.mp3"'
        )
        sys.exit(1)

    sound_type_arg = sys.argv[1]
    file_path_arg = sys.argv[2]

    update_sound_variable(sound_type_arg, file_path_arg)


if __name__ == "__main__":
    main()
