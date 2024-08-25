import Quartz
import time


def is_shift_pressed():
    event_flags = Quartz.CGEventSourceFlagsState(
        Quartz.kCGEventSourceStateHIDSystemState
    )
    return event_flags & Quartz.kCGEventFlagMaskShift


def is_alt_pressed():
    event_flags = Quartz.CGEventSourceFlagsState(
        Quartz.kCGEventSourceStateHIDSystemState
    )
    return event_flags & Quartz.kCGEventFlagMaskAlternate


def is_ctrl_pressed():
    event_flags = Quartz.CGEventSourceFlagsState(
        Quartz.kCGEventSourceStateHIDSystemState
    )
    return event_flags & Quartz.kCGEventFlagMaskControl


def check_modifier_keys():
    shift_state = "pressed" if is_shift_pressed() else "not pressed"
    alt_state = "pressed" if is_alt_pressed() else "not pressed"
    ctrl_state = "pressed" if is_ctrl_pressed() else "not pressed"

    print(f"Shift: {shift_state}, Alt: {alt_state}, Ctrl: {ctrl_state}")


def main():
    print("Press 'q' to quit.")
    while True:
        check_modifier_keys()
        time.sleep(0.5)  # Check every 0.5 seconds

        # Simple key input handling to allow quitting
        if is_key_pressed("q"):
            print("Quitting...")
            break


def is_key_pressed(key):
    # This function captures key presses and checks if a specific key is pressed.
    # Use the built-in input function to wait for key press
    import sys
    import select

    if sys.platform == "darwin":
        # Set a timeout for non-blocking input
        print(f"Waiting for input: ", end="", flush=True)
        i, o, e = select.select([sys.stdin], [], [], 0.5)
        if i:
            key_input = sys.stdin.read(1)
            return key_input == key
        return False


if __name__ == "__main__":
    main()
