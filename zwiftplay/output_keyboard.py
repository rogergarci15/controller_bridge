"""Salidas: teclado real (pynput) y modo de prueba que solo imprime."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def validate_key(name: str) -> None:
    """Comprueba el nombre de una tecla sin necesitar pynput (para config y tests)."""
    if len(name) != 1 and name.lower() not in SPECIAL_KEYS:
        raise ValueError(
            f"tecla `{name}` no reconocida: usa un solo carácter o una de {', '.join(sorted(SPECIAL_KEYS))}"
        )


# Nombres de teclas especiales admitidos; coinciden con pynput.keyboard.Key.
SPECIAL_KEYS = {
    "left", "right", "up", "down", "space", "enter", "esc", "tab", "backspace",
    "shift", "ctrl", "alt", "page_up", "page_down", "home", "end",
    *(f"f{i}" for i in range(1, 13)),
}


class KeyboardOutput:
    """Envía pulsaciones al sistema. En Windows usa SendInput: no necesita
    administrador, pero la ventana de destino (MyWhoosh) tiene que tener el foco.
    """

    def __init__(self) -> None:
        from pynput.keyboard import Controller, Key  # import tardío: no hay teclado en CI

        self._controller = Controller()
        self._key_enum = Key

    def _resolve(self, name: str):
        if len(name) == 1:
            return name.lower()
        return getattr(self._key_enum, name.lower())

    def press(self, key: str) -> None:
        self._controller.press(self._resolve(key))
        log.debug("tecla abajo: %s", key)

    def release(self, key: str) -> None:
        self._controller.release(self._resolve(key))
        log.debug("tecla arriba: %s", key)


class DryRunOutput:
    """No envía nada: imprime lo que enviaría."""

    def press(self, key: str) -> None:
        print(f"    [simulado] tecla ABAJO  {key}", flush=True)

    def release(self, key: str) -> None:
        print(f"    [simulado] tecla arriba {key}", flush=True)


def make_output(method: str = "auto"):
    """Crea la salida de teclado.

    method: "scancode" (SendInput con códigos de escaneo, solo Windows; es lo
    que entienden los juegos), "vk" (pynput) o "auto" (scancode en Windows,
    pynput en el resto).
    """
    import sys

    if method == "auto":
        method = "scancode" if sys.platform == "win32" else "vk"
    if method == "scancode":
        from .output_win32 import ScancodeOutput

        return ScancodeOutput()
    return KeyboardOutput()
