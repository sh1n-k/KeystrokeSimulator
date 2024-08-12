import os
import shutil

from loguru import logger

from keystroke_simulator_app import KeystrokeSimulatorApp

if __name__ == "__main__":
	# Configure Loguru
	log_path = "logs"
	if not os.path.exists(log_path):
		os.mkdir(log_path)
	if os.path.isfile(log_path):
		shutil.move(log_path, "logs.bak")
		os.makedirs(log_path)
	logger.add(os.path.join(log_path, "keysym.log"), rotation="1 MB", level="DEBUG")

	if not os.path.exists("profiles"):
		os.makedirs("profiles")

	app = KeystrokeSimulatorApp()
	app.mainloop()
