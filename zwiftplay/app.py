"""Aplicación de escritorio: una ventana pequeña que mantiene el puente en marcha.

La interfaz (tkinter) vive en el hilo principal y el puente (asyncio + bleak)
en un hilo aparte; se comunican por una cola. Bluetooth no puede ir en el
hilo de la interfaz en Windows.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import queue
import subprocess
import sys
import threading
import time

from . import autostart
from .bridge import Bridge
from .config import Config, ConfigError, ensure_user_config, load_config

APP_NAME = "Zwift Ride → MyWhoosh"
log = logging.getLogger(__name__)


class BridgeThread:
    """Ejecuta el puente en un hilo con su propio bucle de asyncio."""

    def __init__(self, config: Config, events: "queue.Queue[tuple[str, str]]"):
        self._config = config
        self._events = events
        self._loop: asyncio.AbstractEventLoop | None = None
        self._bridge: Bridge | None = None
        self._task: asyncio.Task | None = None
        self._thread = threading.Thread(target=self._run, name="bridge", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        try:
            asyncio.run(self._main())
        except Exception as exc:  # que un fallo inesperado se vea en la ventana
            log.exception("el puente ha fallado")
            self._events.put(("fatal", str(exc)))

    async def _main(self) -> None:
        from .output_keyboard import make_output

        self._loop = asyncio.get_running_loop()
        self._bridge = Bridge(self._config, make_output("auto"), on_status=lambda s, d: self._events.put((s, d)))
        self._task = asyncio.current_task()
        try:
            await self._bridge.run()
        except asyncio.CancelledError:
            pass

    def set_config(self, config: Config) -> None:
        if self._loop and self._bridge:
            self._loop.call_soon_threadsafe(self._bridge.set_config, config)

    def stop(self) -> None:
        if self._loop and self._task:
            self._loop.call_soon_threadsafe(self._task.cancel)
        self._thread.join(timeout=3.0)


def already_running() -> bool:
    """Evita dos copias a la vez: se pelearían por la conexión Bluetooth."""
    if sys.platform != "win32":
        return False
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, "ZwiftRideBridge.SingleInstance")
    already_running.handle = handle  # mantener vivo el mutex mientras dure el proceso
    return ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS


class App:
    def __init__(self, minimized: bool = False):
        import tkinter as tk
        from tkinter import messagebox, ttk

        self.tk, self.messagebox = tk, messagebox
        self.config_path = ensure_user_config()
        try:
            config = load_config(self.config_path)
            config_error = None
        except ConfigError as exc:
            from .config import DEFAULT_CONFIG_PATH

            config, config_error = load_config(DEFAULT_CONFIG_PATH), str(exc)

        self.root = root = tk.Tk()
        root.title(APP_NAME)
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.quit)
        frame = ttk.Frame(root, padding=14)
        frame.grid()

        self.status = tk.StringVar(value="Iniciando…")
        self.battery = tk.StringVar(value="Batería: —")
        self.focus = tk.StringVar(value="")
        self.dot = tk.Label(frame, text="●", font=("Segoe UI", 20), fg="#999999")
        self.dot.grid(row=0, column=0, rowspan=2, padx=(0, 10))
        ttk.Label(frame, textvariable=self.status, font=("Segoe UI", 12, "bold"), width=38).grid(row=0, column=1, sticky="w")
        ttk.Label(frame, textvariable=self.battery).grid(row=1, column=1, sticky="w")
        ttk.Label(frame, textvariable=self.focus, foreground="#555555").grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))

        self.log_box = tk.Text(frame, height=7, width=52, state="disabled", font=("Consolas", 9), background="#f4f4f4", relief="flat")
        self.log_box.grid(row=3, column=0, columnspan=2, pady=10)

        self.autostart = tk.BooleanVar(value=autostart.is_enabled())
        check = ttk.Checkbutton(frame, text="Iniciar con Windows (minimizada)", variable=self.autostart, command=self.toggle_autostart)
        check.grid(row=4, column=0, columnspan=2, sticky="w")
        if not autostart.is_supported():
            check.state(["disabled"])

        buttons = ttk.Frame(frame)
        buttons.grid(row=5, column=0, columnspan=2, pady=(10, 0), sticky="w")
        ttk.Button(buttons, text="Editar botones…", command=self.edit_config).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(buttons, text="Aplicar cambios", command=self.reload_config).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(buttons, text="Salir", command=self.quit).grid(row=0, column=2)

        self.events: "queue.Queue[tuple[str, str]]" = queue.Queue()
        self.bridge = BridgeThread(config, self.events)
        self.bridge.start()
        self.add_log(f"Configuración: {self.config_path}")
        if config_error:
            self.add_log(f"Configuración no válida, uso la de fábrica: {config_error}")
        if minimized:
            root.iconify()
        root.after(100, self.poll)

    # --- estado ---------------------------------------------------------------
    def add_log(self, text: str) -> None:
        box = self.log_box
        box.configure(state="normal")
        box.insert("end", f"{time.strftime('%H:%M:%S')}  {text}\n")
        if int(box.index("end-1c").split(".")[0]) > 200:
            box.delete("1.0", "50.0")
        box.see("end")
        box.configure(state="disabled")

    def set_status(self, text: str, color: str) -> None:
        self.status.set(text)
        self.dot.configure(fg=color)

    def poll(self) -> None:
        try:
            while True:
                self.on_event(*self.events.get_nowait())
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def on_event(self, state: str, detail: str) -> None:
        if state == "searching":
            if self.status.get() != "Buscando los mandos…":
                self.set_status("Buscando los mandos…", "#e0a000")
                self.focus.set("Enciende los mandos. Zwift y Companion, cerrados.")
        elif state == "connecting":
            self.set_status("Conectando…", "#e0a000")
        elif state == "connected":
            self.set_status("Conectado", "#2e9e44")
            self.focus.set("")
            self.add_log(f"Conectado (firmware {detail})")
        elif state == "disconnected":
            self.set_status("Reconectando…", "#e0a000")
            self.battery.set("Batería: —")
            self.add_log(f"Conexión perdida: {detail}")
        elif state == "error":
            self.set_status("Problema de conexión", "#d04040")
            self.add_log(detail)
        elif state == "battery":
            self.battery.set(f"Batería: {detail} %")
        elif state == "low_battery":
            self.add_log(f"¡Batería baja ({detail} %)! Carga los mandos.")
            self.battery.set(f"Batería: {detail} %  ¡BAJA!")
        elif state == "focus":
            self.focus.set(
                "MyWhoosh en primer plano: los botones actúan." if detail == "on"
                else "MyWhoosh no está en primer plano: los botones se ignoran."
            )
        elif state == "fatal":
            self.set_status("El puente se ha detenido", "#d04040")
            self.add_log(f"Error inesperado: {detail}. Cierra y vuelve a abrir la aplicación.")

    # --- acciones -------------------------------------------------------------
    def toggle_autostart(self) -> None:
        try:
            autostart.set_enabled(self.autostart.get())
        except (OSError, RuntimeError) as exc:
            self.autostart.set(autostart.is_enabled())
            self.messagebox.showerror(APP_NAME, f"No se pudo cambiar el arranque automático:\n{exc}")

    def edit_config(self) -> None:
        try:
            if sys.platform == "win32":
                subprocess.Popen(["notepad.exe", str(self.config_path)])
            else:
                subprocess.Popen(["xdg-open", str(self.config_path)])
        except OSError as exc:
            self.messagebox.showerror(APP_NAME, f"No se pudo abrir el editor:\n{exc}\n\nFichero: {self.config_path}")
            return
        self.add_log("Edita, guarda y pulsa «Aplicar cambios».")

    def reload_config(self) -> None:
        try:
            config = load_config(self.config_path)
        except ConfigError as exc:
            self.messagebox.showerror(APP_NAME, f"La configuración tiene un error y no se ha aplicado:\n\n{exc}")
            return
        self.bridge.set_config(config)
        self.add_log(f"Configuración aplicada ({len(config.bindings)} controles).")

    def quit(self) -> None:
        self.bridge.stop()  # suelta teclas y desconecta
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def selftest() -> int:
    """Comprueba que el ejecutable lleva dentro todo lo que necesita (para CI)."""
    import bleak  # noqa: F401
    import yaml  # noqa: F401
    from bleak import BleakClient, BleakScanner  # noqa: F401

    from .config import DEFAULT_CONFIG_PATH
    from .output_keyboard import make_output

    config = load_config(DEFAULT_CONFIG_PATH)
    assert config.bindings, "configuración por defecto vacía"
    if sys.platform == "win32":
        from bleak.backends.winrt.scanner import BleakScannerWinRT  # noqa: F401
        from bleak.backends.winrt.client import BleakClientWinRT  # noqa: F401

        make_output("scancode")
    import tkinter  # noqa: F401

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ZwiftRideBridge")
    parser.add_argument("--minimized", action="store_true", help="arrancar con la ventana minimizada")
    parser.add_argument("--selftest", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.selftest:
        try:
            return selftest()
        except Exception:
            import traceback

            # Sin consola en el ejecutable: dejar el error donde CI pueda leerlo.
            with open(os.environ.get("ZRB_SELFTEST_LOG", "selftest-error.txt"), "w", encoding="utf-8") as fh:
                traceback.print_exc(file=fh)
            return 1
    logging.basicConfig(level=logging.INFO)
    if already_running():
        import tkinter as tk
        from tkinter import messagebox

        hidden = tk.Tk()
        hidden.withdraw()
        messagebox.showinfo(APP_NAME, "La aplicación ya está abierta (búscala en la barra de tareas).")
        return 0
    App(minimized=args.minimized).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
