"""macOS 오버레이 창 조정: 전체화면 앱과 다른 Space 위에도 보이게 한다.

Qt의 `WindowStaysOnTopHint`는 같은 Space의 일반 창 위까지만 보장한다.
`winId()`로 얻은 NSView의 NSWindow에 level과 collectionBehavior를 직접
설정한다. Qt는 창을 보이거나 플래그를 바꿀 때 level을 다시 계산하므로
`show()` 뒤에 부른다. macOS가 아니거나 네이티브 창이 없으면(offscreen) 아무것도
하지 않는다.
"""

from __future__ import annotations

import importlib
import sys
from typing import Any

from loguru import logger
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget

# NSStatusWindowLevel. 일반 floating(3)보다 높아 전체화면 게임 위에 뜬다.
_OVERLAY_LEVEL_NAME = "NSStatusWindowLevel"


def keep_above_all_spaces(widget: QWidget) -> bool:
    """적용했으면 True. 실패해도 창은 Qt의 항상 위 상태로 남는다."""
    if sys.platform != "darwin" or QGuiApplication.platformName() != "cocoa":
        return False
    try:
        objc: Any = importlib.import_module("objc")
        appkit: Any = importlib.import_module("AppKit")
        view: Any = objc.objc_object(c_void_p=int(widget.winId()))
        window: Any = view.window()
        if window is None:
            return False
        window.setCollectionBehavior_(
            appkit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | appkit.NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        window.setLevel_(getattr(appkit, _OVERLAY_LEVEL_NAME))
    except Exception as exc:  # PyObjC 누락·NSWindow 변경 실패는 치명적이지 않다.
        logger.debug(f"NSWindow overlay setup skipped: {exc!r}")
        return False
    return True
