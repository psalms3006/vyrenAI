"""
vision/windows_grab.py -- Windows-native screen capture fallback.

Uses ctypes/GDI to capture monitor regions without external
dependencies such as mss or Pillow.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import threading
from dataclasses import dataclass
from typing import Sequence

logger = logging.getLogger("vyren.vision")

user32 = ctypes.windll.user32  # type: ignore[attr-defined]
gdi32 = ctypes.windll.gdi32  # type: ignore[attr-defined]


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.wintypes.LONG),
        ("top", ctypes.wintypes.LONG),
        ("right", ctypes.wintypes.LONG),
        ("bottom", ctypes.wintypes.LONG),
    ]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", ctypes.wintypes.WORD),
        ("biBitCount", ctypes.wintypes.WORD),
        ("biCompression", ctypes.wintypes.DWORD),
        ("biSizeImage", ctypes.wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", ctypes.wintypes.DWORD),
        ("biClrImportant", ctypes.wintypes.DWORD),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("biClr", ctypes.c_ubyte * 3)]


@dataclass(frozen=True)
class MonitorRect:
    index: int = 0
    left: int = 0
    top: int = 0
    width: int = 0
    height: int = 0

    @property
    def box(self) -> tuple[int, int, int, int]:
        return (self.left, self.top, self.left + self.width, self.top + self.height)


class MonitorCapture:
    """Capture full monitor images as raw BGRA byte strings."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._monitors: list[MonitorRect] = []
        self.refresh()

    def refresh(self) -> None:
        def enum_callback(_hmonitor, _hdc, ptr, _data):
            try:
                rect = ctypes.cast(ptr, ctypes.POINTER(_RECT)).contents
                width = rect.right - rect.left
                height = rect.bottom - rect.top
                if width <= 0 or height <= 0:
                    return True
                self._monitors.append(
                    MonitorRect(
                        index=len(self._monitors),
                        left=rect.left,
                        top=rect.top,
                        width=width,
                        height=height,
                    )
                )
            except Exception as exc:
                logger.debug("Monitor enum callback failed: %s", exc)
            return True

        self._monitors = []
        monitor_enum = ctypes.WINFUNCTYPE(
            ctypes.c_bool, ctypes.wintypes.HMONITOR, ctypes.wintypes.HDC,
            ctypes.POINTER(_RECT), ctypes.wintypes.LPARAM
        )(enum_callback)
        user32.EnumDisplayMonitors(0, 0, monitor_enum, 0)
        if not self._monitors:
            try:
                width = user32.GetSystemMetrics(0)
                height = user32.GetSystemMetrics(1)
                self._monitors.append(
                    MonitorRect(index=0, left=0, top=0, width=width, height=height)
                )
            except Exception:
                self._monitors.append(MonitorRect(index=0, left=0, top=0, width=320, height=240))

    @property
    def monitors(self) -> Sequence[MonitorRect]:
        with self._lock:
            return list(self._monitors)

    def capture(self, monitor: MonitorRect) -> bytes | None:
        try:
            hdc_screen = user32.GetDC(0)
            hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
            hbitmap = gdi32.CreateCompatibleBitmap(
                hdc_screen, monitor.width, monitor.height
            )
            gdi32.SelectObject(hdc_mem, hbitmap)

            gdi32.BitBlt(
                hdc_mem,
                0,
                0,
                monitor.width,
                monitor.height,
                hdc_screen,
                monitor.left,
                monitor.top,
                0x00CC0020,  # SRCCOPY
            )

            bmi = _BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = monitor.width
            bmi.bmiHeader.biHeight = -monitor.height
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 24

            row_bytes = ((monitor.width * 3 + 3) // 4) * 4
            buf = ctypes.create_string_buffer(row_bytes * monitor.height)
            scan = gdi32.GetDIBits(
                hdc_mem,
                hbitmap,
                0,
                monitor.height,
                ctypes.byref(buf),
                ctypes.byref(bmi),
                0,
            )
            gdi32.DeleteObject(hbitmap)
            gdi32.DeleteDC(hdc_mem)
            user32.ReleaseDC(0, hdc_screen)

            if scan != monitor.height:
                return None
            return buf.raw
        except Exception as exc:
            logger.debug("Monitor capture failed: %s", exc)
            return None
