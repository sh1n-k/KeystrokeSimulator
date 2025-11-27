import signal
import sys
from pathlib import Path
from loguru import logger

def main():
    log_path = Path("logs")
    log_path.mkdir(exist_ok=True)
    
    logger.add(log_path / "keysym.log", rotation="1 MB", level="INFO", enqueue=True)
    Path("profiles").mkdir(exist_ok=True)
    
    from keystroke_simulator_app import KeystrokeSimulatorApp
    app = None
    
    def graceful_shutdown(signum=None, frame=None):
        if app:
            app.after(0, app.on_closing)
    
    signal.signal(signal.SIGINT, graceful_shutdown)
    signal.signal(signal.SIGTERM, graceful_shutdown)
    
    try:
        app = KeystrokeSimulatorApp()
        logger.info("Application started.")
        app.mainloop()
    except (KeyboardInterrupt, Exception) as e:
        logger.info(f"Shutting down: {e}")
        if app:
            app.on_closing()
    finally:
        logger.info("Application terminated.")

if __name__ == "__main__":
    main()