"""Consulta de la ventana activa (solo Windows)."""

from __future__ import annotations

import sys


def foreground_title() -> str | None:
    """Título de la ventana en primer plano, o None si no se puede saber.

    API Win32 documentada: GetForegroundWindow, GetWindowTextW.
    """
    if sys.platform != "win32":
        return None
    import ctypes

    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    user32.GetWindowTextW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int)
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buffer, 256)
    return buffer.value


def is_focused(wanted: str) -> bool:
    """¿La ventana activa contiene `wanted` en el título?

    Si no se pide ninguna ventana, o el sistema no permite saberlo, devuelve
    True (no se bloquea nada).
    """
    if not wanted:
        return True
    title = foreground_title()
    if title is None:
        return True
    return wanted.lower() in title.lower()
