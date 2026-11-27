"""BlueStacks window detection and screenshot capture (read-only; sends no input to the game)."""
from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional

import numpy as np

WINDOW_KEYWORDS = ("bluestacks", "app player")


def list_windows() -> List[Dict[str, Any]]:
    """Visible top-level windows whose title looks like BlueStacks (Windows only)."""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass
    found: List[Dict[str, Any]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if not length:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value
        if any(k in title.lower() for k in WINDOW_KEYWORDS):
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            found.append({"hwnd": int(hwnd), "title": title, "left": rect.left, "top": rect.top,
                          "width": rect.right - rect.left, "height": rect.bottom - rect.top})
        return True

    user32.EnumWindows(cb, 0)
    return found


def capture(window: Optional[Dict[str, Any]] = None) -> Optional[np.ndarray]:
    """Grab the BlueStacks window region (or the first one found). Needs ``mss``."""
    if window is None:
        wins = list_windows()
        if not wins:
            return None
        window = max(wins, key=lambda w: w["width"] * w["height"])
    try:
        import mss  # type: ignore
    except ImportError:
        raise RuntimeError("Screen capture needs the 'mss' package (pip install mss).")
    with mss.mss() as sct:
        shot = sct.grab({"left": window["left"], "top": window["top"],
                         "width": window["width"], "height": window["height"]})
        img = np.array(shot)[:, :, :3]  # BGRA -> BGR
        return np.ascontiguousarray(img)
