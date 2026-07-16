import signal
from collections.abc import Callable
from pathlib import Path
from types import FrameType
from typing import Protocol, cast

from loguru import logger

from app.ui.simulator_app import KeystrokeSimulatorApp
from app.utils.system import install_exception_hooks


class MainAppLike(Protocol):
    def after(
        self, _ms: int, func: Callable[..., object] | None = None, *args: object
    ) -> object: ...
    def mainloop(self) -> object: ...
    def on_closing(self) -> None: ...


def main() -> None:
    log_path = Path("logs")
    log_path.mkdir(exist_ok=True)

    log_handler_id = logger.add(
        log_path / "keysym.log",
        rotation="1 MB",
        level="INFO",
        enqueue=False,
    )
    install_exception_hooks()
    Path("profiles").mkdir(exist_ok=True)

    app: MainAppLike | None = None

    def graceful_shutdown(_signum: int, _frame: FrameType | None) -> None:
        if app:
            app.after(0, app.on_closing)

    signal.signal(signal.SIGINT, graceful_shutdown)
    signal.signal(signal.SIGTERM, graceful_shutdown)

    try:
        app = cast(MainAppLike, KeystrokeSimulatorApp())
        logger.info("Application started.")
        app.mainloop()
    except (KeyboardInterrupt, Exception) as e:
        logger.info(f"Shutting down: {e}")
        if app:
            app.on_closing()
    finally:
        logger.info("Application terminated.")
        logger.remove(log_handler_id)


if __name__ == "__main__":
    main()
