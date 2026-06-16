"""Native (win32) frameless chrome: a borderless window that keeps Aero Snap.

Going frameless with ``Qt.FramelessWindowHint`` removes the native title bar but
also strips ``WS_THICKFRAME`` - so Windows stops doing resize, Aero Snap, the
maximize animation, and the drop shadow. To keep all of that we instead leave the
window native and intercept two non-client messages:

- ``WM_NCCALCSIZE`` - tell Windows the client area fills the whole window, which
  removes the title bar and borders *visually* while the real (snappable,
  resizable) native window stays underneath.
- ``WM_NCHITTEST`` - report which pixels are the resize borders and which are the
  draggable caption, so the DWM move/resize loops (and therefore snap) kick in.

Only the win32 path lives here; ``chrome.install_resize_grips`` is the portable
fallback for other platforms. ``MainWindow.nativeEvent`` forwards to ``handle``.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

# --- win32 constants -------------------------------------------------------
_GWL_STYLE = -16
_WS_THICKFRAME = 0x00040000
_WS_CAPTION = 0x00C00000
_WS_MAXIMIZEBOX = 0x00010000
_WS_MINIMIZEBOX = 0x00020000
_WS_SYSMENU = 0x00080000

_WM_NCCALCSIZE = 0x0083
_WM_NCHITTEST = 0x0084

_SM_CXSIZEFRAME = 32
_SM_CYSIZEFRAME = 33
_SM_CXPADDEDBORDER = 92

_SWP_FRAMECHANGED = 0x0020
_SWP_NOMOVE = 0x0002
_SWP_NOSIZE = 0x0001
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010

# WM_NCHITTEST return codes for the resize border + caption.
_HTCLIENT = 1
_HTCAPTION = 2
_HTLEFT = 10
_HTRIGHT = 11
_HTTOP = 12
_HTTOPLEFT = 13
_HTTOPRIGHT = 14
_HTBOTTOM = 15
_HTBOTTOMLEFT = 16
_HTBOTTOMRIGHT = 17

_BORDER = 8  # px resize-grip zone along each edge


class _MARGINS(ctypes.Structure):
    _fields_ = [("cxLeftWidth", ctypes.c_int), ("cxRightWidth", ctypes.c_int),
                ("cyTopHeight", ctypes.c_int), ("cyBottomHeight", ctypes.c_int)]


class _NCCALCSIZE_PARAMS(ctypes.Structure):
    _fields_ = [("rgrc", wintypes.RECT * 3), ("lppos", ctypes.c_void_p)]


def _user32():
    return ctypes.windll.user32


def enable(window) -> bool:
    """Make ``window`` borderless but natively resizable/snappable. Returns True if
    the native styles were applied (win32 only); False if anything went wrong, so
    the caller can fall back to the portable grips."""
    try:
        hwnd = int(window.winId())
        user32 = _user32()
        get_style = user32.GetWindowLongPtrW if hasattr(user32, "GetWindowLongPtrW") \
            else user32.GetWindowLongW
        set_style = user32.SetWindowLongPtrW if hasattr(user32, "SetWindowLongPtrW") \
            else user32.SetWindowLongW
        style = get_style(hwnd, _GWL_STYLE)
        # Keep the frame styles DWM needs for snap/shadow/animation; NCCALCSIZE hides
        # the title bar that WS_CAPTION would otherwise draw.
        style |= (_WS_THICKFRAME | _WS_CAPTION | _WS_MAXIMIZEBOX
                  | _WS_MINIMIZEBOX | _WS_SYSMENU)
        set_style(hwnd, _GWL_STYLE, style)
        # A 1px frame extension lights up the DWM drop shadow.
        try:
            margins = _MARGINS(0, 0, 1, 0)
            ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(
                hwnd, ctypes.byref(margins))
        except Exception:
            pass
        user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                            _SWP_FRAMECHANGED | _SWP_NOMOVE | _SWP_NOSIZE
                            | _SWP_NOZORDER | _SWP_NOACTIVATE)
        return True
    except Exception:
        return False


def _is_maximized(hwnd) -> bool:
    placement = (ctypes.c_int * 11)()
    placement[0] = ctypes.sizeof(placement)
    try:
        _user32().GetWindowPlacement(hwnd, ctypes.byref(placement))
        return placement[1] == 3  # SW_SHOWMAXIMIZED
    except Exception:
        return False


def handle(window, message, is_caption):
    """Process a native message for the borderless window. ``is_caption`` is a
    callback taking a window-local (x, y) in device-independent pixels and
    returning True if that point is the draggable title-bar region.

    Returns ``(handled, result)`` to return from ``nativeEvent``, or ``None`` to let
    Qt handle the message normally."""
    msg = wintypes.MSG.from_address(int(message))
    if msg.message == _WM_NCCALCSIZE and msg.wParam:
        # Client area = whole window (title bar/borders removed). When maximized,
        # inset by the frame so content doesn't spill past the screen/taskbar.
        hwnd = msg.hWnd
        if _is_maximized(hwnd):
            params = _NCCALCSIZE_PARAMS.from_address(msg.lParam)
            user32 = _user32()
            bx = (user32.GetSystemMetrics(_SM_CXSIZEFRAME)
                  + user32.GetSystemMetrics(_SM_CXPADDEDBORDER))
            by = (user32.GetSystemMetrics(_SM_CYSIZEFRAME)
                  + user32.GetSystemMetrics(_SM_CXPADDEDBORDER))
            params.rgrc[0].left += bx
            params.rgrc[0].top += by
            params.rgrc[0].right -= bx
            params.rgrc[0].bottom -= by
        return True, 0

    if msg.message == _WM_NCHITTEST:
        hwnd = msg.hWnd
        # lParam packs signed screen x (low word) / y (high word).
        x = ctypes.c_short(msg.lParam & 0xFFFF).value
        y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
        rect = wintypes.RECT()
        _user32().GetWindowRect(hwnd, ctypes.byref(rect))
        ratio = window.devicePixelRatioF()
        lx = x - rect.left
        ly = y - rect.top
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        maximized = _is_maximized(hwnd)
        b = _BORDER
        if not maximized:
            on_left = lx < b
            on_right = lx >= w - b
            on_top = ly < b
            on_bottom = ly >= h - b
            if on_top and on_left:
                return True, _HTTOPLEFT
            if on_top and on_right:
                return True, _HTTOPRIGHT
            if on_bottom and on_left:
                return True, _HTBOTTOMLEFT
            if on_bottom and on_right:
                return True, _HTBOTTOMRIGHT
            if on_left:
                return True, _HTLEFT
            if on_right:
                return True, _HTRIGHT
            if on_top:
                return True, _HTTOP
            if on_bottom:
                return True, _HTBOTTOM
        # Caption test runs in device-independent pixels (what Qt widgets use).
        if is_caption(lx / ratio, ly / ratio):
            return True, _HTCAPTION
        return True, _HTCLIENT

    return None
