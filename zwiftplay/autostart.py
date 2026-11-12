"""Arranque automático con Windows, sin administrador.

Usa la clave de registro del usuario
HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run (documentada por
Microsoft como "Run and RunOnce Registry Keys").
"""

from __future__ import annotations

import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "ZwiftRideBridge"


def launch_command() -> str:
    """Orden que arranca esta misma aplicación, minimizada."""
    if getattr(sys, "frozen", False):  # ejecutable de PyInstaller
        return f'"{sys.executable}" --minimized'
    python = Path(sys.executable)
    windowless = python.with_name("pythonw.exe")  # sin ventana de consola
    return f'"{windowless if windowless.exists() else python}" -m zwiftplay app --minimized'


def is_supported() -> bool:
    return sys.platform == "win32"


def is_enabled() -> bool:
    if not is_supported():
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
    except OSError:
        return False
    return value == launch_command()


def set_enabled(enabled: bool) -> None:
    if not is_supported():
        raise RuntimeError("el arranque automático solo está disponible en Windows")
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
