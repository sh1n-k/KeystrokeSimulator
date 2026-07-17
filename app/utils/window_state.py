import ast
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol, cast

from loguru import logger


class WindowLike(Protocol):
    def update_idletasks(self) -> None: ...
    def winfo_screenwidth(self) -> int: ...
    def winfo_screenheight(self) -> int: ...
    def winfo_width(self) -> int: ...
    def winfo_height(self) -> int: ...
    def geometry(self, _new_geometry: str) -> object: ...


class WindowUtils:
    @staticmethod
    def center_window(win: object) -> None:
        window = cast(WindowLike, win)
        window.update_idletasks()
        x = (window.winfo_screenwidth() - window.winfo_width()) // 2
        y = (window.winfo_screenheight() - window.winfo_height()) // 2
        window.geometry(f"+{x}+{y}")


class StateUtils:
    path = Path("./app_state.json")

    @classmethod
    def save_main_app_state(cls, **kwargs: object) -> None:
        try:
            data = cls.load_main_app_state()
            data.update({k: v for k, v in kwargs.items() if v is not None})
            tmp = cls.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            tmp.replace(cls.path)
        except Exception as e:
            logger.error(f"Save state failed: {e}")

    @classmethod
    def load_main_app_state(cls) -> dict[str, object]:
        if not cls.path.exists():
            return {}
        try:
            data: object = json.loads(cls.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                logger.error(
                    f"Load state failed: expected object, got {type(data).__name__}"
                )
                return {}
            raw_data = cast(Mapping[object, object], data)
            return {str(k): v for k, v in raw_data.items()}
        except Exception as e:
            logger.error(f"Load state failed: {e}")
            return {}

    @staticmethod
    def parse_slash_int_pair(raw: object) -> tuple[int, int] | None:
        if raw is None:
            return None
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
            seq = cast(Sequence[object], raw)
            if len(seq) < 2:
                return None
            first, second = seq[0], seq[1]
            if not isinstance(first, (int, float, str)) or not isinstance(
                second, (int, float, str)
            ):
                return None
            try:
                return (int(first), int(second))
            except (TypeError, ValueError, OverflowError):
                return None
        if not isinstance(raw, str):
            return None
        parts = raw.split("/", 1)
        if len(parts) != 2:
            return None
        try:
            return (int(parts[0]), int(parts[1]))
        except (TypeError, ValueError, OverflowError):
            return None

    @staticmethod
    def parse_position_tuple(raw: object) -> tuple[int, int] | None:
        if raw is None:
            return None
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
            seq = cast(Sequence[object], raw)
            if len(seq) < 2:
                return None
            first, second = seq[0], seq[1]
            if not isinstance(first, (int, float, str)) or not isinstance(
                second, (int, float, str)
            ):
                return None
            try:
                return (int(first), int(second))
            except (TypeError, ValueError, OverflowError):
                return None
        if not isinstance(raw, str):
            return None
        try:
            parsed = ast.literal_eval(raw)
        except (SyntaxError, ValueError):
            return None
        if not isinstance(parsed, Sequence) or isinstance(
            parsed, (str, bytes, bytearray)
        ):
            return None
        seq = cast(Sequence[object], parsed)
        if len(seq) < 2:
            return None
        first, second = seq[0], seq[1]
        if not isinstance(first, (int, float, str)) or not isinstance(
            second, (int, float, str)
        ):
            return None
        try:
            return (int(first), int(second))
        except (TypeError, ValueError, OverflowError):
            return None
