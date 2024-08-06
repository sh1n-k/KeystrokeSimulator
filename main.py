import os

from loguru import logger

from keystroke_simulator_app import KeystrokeSimulatorApp

if __name__ == "__main__":
    # Configure Loguru
    logger.add("_keystroke_simulator.log", rotation="1 MB", level="DEBUG")

    if not os.path.exists("profiles"):
        os.makedirs("profiles")

    app = KeystrokeSimulatorApp()
    app.mainloop()
