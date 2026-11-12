"""Salida de teclado para Windows con SendInput y códigos de escaneo.

Muchos juegos leen el teclado a bajo nivel (códigos de escaneo) e ignoran las
pulsaciones simuladas que solo llevan tecla virtual. Aquí se envía el código
de escaneo con KEYEVENTF_SCANCODE y wVk = 0, que es lo mismo que hace
BikeControl para MyWhoosh ([BC] keypress_simulator_windows_plugin.cpp).

Constantes y estructuras: API Win32 documentada por Microsoft (SendInput,
INPUT, KEYBDINPUT, MapVirtualKeyW, VkKeyScanW, "Virtual-Key Codes").
No necesita administrador, salvo que el juego se ejecute como administrador.
"""

from __future__ import annotations

import ctypes
import logging
import sys

log = logging.getLogger(__name__)

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
MAPVK_VK_TO_VSC = 0
INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001  # movimiento relativo
MOUSE_BUTTON_FLAGS = {  # (pulsar, soltar): MOUSEEVENTF_LEFTDOWN/LEFTUP, RIGHTDOWN/RIGHTUP
    "left": (0x0002, 0x0004),
    "right": (0x0008, 0x0010),
}

# Teclas virtuales de las teclas con nombre (tabla "Virtual-Key Codes").
VIRTUAL_KEYS = {
    "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "shift": 0x10, "ctrl": 0x11,
    "alt": 0x12, "esc": 0x1B, "space": 0x20, "page_up": 0x21, "page_down": 0x22,
    "end": 0x23, "home": 0x24, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    **{f"f{i}": 0x6F + i for i in range(1, 13)},
}
# Teclas del bloque "extendido": necesitan KEYEVENTF_EXTENDEDKEY o el sistema
# las toma por las del teclado numérico.
EXTENDED_KEYS = {"left", "up", "right", "down", "page_up", "page_down", "home", "end"}

_ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_int32), ("dy", ctypes.c_int32), ("mouseData", ctypes.c_uint32),
                ("dwFlags", ctypes.c_uint32), ("time", ctypes.c_uint32), ("dwExtraInfo", _ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_uint16), ("wScan", ctypes.c_uint16), ("dwFlags", ctypes.c_uint32),
                ("time", ctypes.c_uint32), ("dwExtraInfo", _ULONG_PTR)]


class _INPUT_UNION(ctypes.Union):
    # MOUSEINPUT es el miembro más grande: sin él, el tamaño de INPUT sería
    # incorrecto y SendInput rechazaría la llamada.
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.c_uint32), ("u", _INPUT_UNION)]


def build_input(scan: int, extended: bool, down: bool) -> INPUT:
    flags = KEYEVENTF_SCANCODE
    if extended:
        flags |= KEYEVENTF_EXTENDEDKEY
    if not down:
        flags |= KEYEVENTF_KEYUP
    item = INPUT(type=INPUT_KEYBOARD)
    item.ki = KEYBDINPUT(wVk=0, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0)
    return item


def build_mouse_input(flags: int, dx: int = 0, dy: int = 0) -> INPUT:
    item = INPUT(type=INPUT_MOUSE)
    item.mi = MOUSEINPUT(dx=dx, dy=dy, mouseData=0, dwFlags=flags, time=0, dwExtraInfo=0)
    return item


class ScancodeOutput:
    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("ScancodeOutput solo funciona en Windows")
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.SendInput.argtypes = (ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int)
        self._user32.SendInput.restype = ctypes.c_uint
        self._user32.MapVirtualKeyW.argtypes = (ctypes.c_uint, ctypes.c_uint)
        self._user32.MapVirtualKeyW.restype = ctypes.c_uint
        self._user32.VkKeyScanW.argtypes = (ctypes.c_wchar,)
        self._user32.VkKeyScanW.restype = ctypes.c_short
        self._cache: dict[str, tuple[int, bool]] = {}
        self._warned = False

    def _lookup(self, key: str) -> tuple[int, bool]:
        name = key.lower()
        if name not in self._cache:
            if name in VIRTUAL_KEYS:
                vk = VIRTUAL_KEYS[name]
            else:
                result = self._user32.VkKeyScanW(name)
                if result == -1:
                    raise ValueError(f"la tecla `{key}` no existe en la distribución de teclado actual")
                vk = result & 0xFF
            scan = self._user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
            if scan == 0:
                raise ValueError(f"no hay código de escaneo para la tecla `{key}`")
            self._cache[name] = (scan, name in EXTENDED_KEYS)
        return self._cache[name]

    def _send(self, key: str, down: bool) -> None:
        scan, extended = self._lookup(key)
        item = build_input(scan, extended, down)
        sent = self._user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(INPUT))
        if sent != 1 and not self._warned:
            self._warned = True
            log.warning(
                "Windows ha rechazado la pulsación (error %s). Suele pasar si la ventana activa "
                "se ejecuta como administrador.", ctypes.get_last_error(),
            )
        log.debug("tecla %s: %s (scan %#x)", "abajo" if down else "arriba", key, scan)

    def press(self, key: str) -> None:
        self._send(key, True)

    def release(self, key: str) -> None:
        self._send(key, False)

    def _send_mouse(self, item: INPUT) -> None:
        if self._user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(INPUT)) != 1 and not self._warned:
            self._warned = True
            log.warning("Windows ha rechazado el evento de ratón (error %s).", ctypes.get_last_error())

    def mouse_move(self, dx: int, dy: int) -> None:
        self._send_mouse(build_mouse_input(MOUSEEVENTF_MOVE, dx, dy))

    def mouse_button(self, button: str, down: bool) -> None:
        self._send_mouse(build_mouse_input(MOUSE_BUTTON_FLAGS[button][0 if down else 1]))
