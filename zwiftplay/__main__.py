"""Línea de órdenes: `python -m zwiftplay <orden>`."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

from .protocol import (
    AnalogEvent, Battery, ButtonEvent, ControllerState, HandshakeAck, Idle, Keypad, Message, Unknown, decode,
)

SIDE_ES = {"left": "IZQ ", "right": "DCHA"}


class MonitorPrinter:
    """Imprime los eventos de forma legible."""

    def __init__(self, show_all: bool = False):
        self.state = ControllerState()
        self.show_all = show_all
        self.battery: int | None = None
        self.start = time.monotonic()

    def _line(self, text: str, at: float | None = None) -> None:
        stamp = at if at is not None else time.monotonic() - self.start
        print(f"[{stamp:8.2f}] {text}", flush=True)

    def handle(self, message: Message, at: float | None = None) -> None:
        if isinstance(message, Keypad):
            if message.unknown_bits:
                self._line(f"??   bits desconocidos pulsados: {message.unknown_bits:#x}", at)
            for event in self.state.update(message):
                if isinstance(event, ButtonEvent):
                    action = "PULSADO" if event.pressed else "suelto"
                    self._line(f"{SIDE_ES[event.side]} {event.button:<12} {action}", at)
                elif isinstance(event, AnalogEvent):
                    bar = "#" * (abs(event.value) // 5)
                    self._line(f"{SIDE_ES[event.side]} {event.axis:<12} {event.value:>4}  {bar}", at)
        elif isinstance(message, Battery):
            if message.level != self.battery:
                self.battery = message.level
                self._line(f"batería {message.level} %", at)
        elif isinstance(message, HandshakeAck):
            self._line("handshake aceptado" + (f" (extra: {message.extra.hex()})" if message.extra else ""), at)
        elif isinstance(message, Idle):
            if self.show_all:
                self._line("reposo", at)
        elif isinstance(message, Unknown) and self.show_all:
            self._line(f"tipo {message.type:#04x}: {message.body.hex()}", at)


def replay(path: Path, show_all: bool) -> int:
    """Reproduce una captura de tools/sniff.py como si llegara del mando."""
    from .capture import read_capture

    printer = MonitorPrinter(show_all)
    first: float | None = None
    for record in read_capture(path):
        if first is None:
            first = record["mono"]
        at = record["mono"] - first
        if record["type"] == "label" and record["phase"] == "start":
            print(f"--- paso: {record['label']}")
        elif record["type"] == "rx":
            printer.handle(decode(bytes.fromhex(record["hex"])), at)
    return 0


async def monitor(args: argparse.Namespace) -> int:
    from bleak.exc import BleakError

    from .client import RideConnection, find_controller

    print(f"Buscando el mando ({args.scan_time:.0f} s)… Zwift y Companion tienen que estar cerrados.")
    try:
        found = await find_controller(args.scan_time, args.address)
    except (BleakError, OSError) as exc:
        print(f"Error de Bluetooth: {exc}")
        return 2
    if found is None:
        print("No se ha encontrado ningún mando compatible. Prueba `python tools/scan.py`.")
        return 1

    printer = MonitorPrinter(args.all)
    connection = RideConnection(found, printer.handle)
    try:
        await connection.connect()
    except (BleakError, asyncio.TimeoutError, OSError, RuntimeError) as exc:
        print(f"No se pudo conectar a {found.label}: {exc}")
        return 1
    print(f"Conectado a {found.label} (firmware {connection.firmware}). Pulsa botones; Ctrl+C para salir.\n")
    try:
        await connection.disconnected.wait()
        print("\nEl mando se ha desconectado.")
    finally:
        await connection.disconnect()
    return 0


def keytest(args: argparse.Namespace) -> int:
    """Envía una tecla varias veces, sin mandos: sirve para ver si el juego la recibe."""
    from .output_keyboard import make_output

    output = make_output(args.method)
    print(f"En {args.delay:.0f} s enviaré la tecla `{args.key}` {args.count} veces (método: {args.method}).")
    print("Cambia YA a la ventana donde quieras probarla (MyWhoosh, o el Bloc de notas).")
    time.sleep(args.delay)
    for index in range(args.count):
        output.press(args.key)
        time.sleep(args.hold_ms / 1000.0)
        output.release(args.key)
        print(f"  enviada {index + 1}/{args.count}", flush=True)
        time.sleep(1.0)
    return 0


STATUS_TEXT = {
    "searching": "Buscando el mando… (enciéndelo; Zwift y Companion cerrados)",
    "connecting": "Mando encontrado, conectando: {detail}",
    "connected": "CONECTADO (firmware {detail})",
    "disconnected": "Conexión perdida: {detail}. Reconectando…",
    "error": "Error: {detail}",
    "battery": "Batería: {detail} %",
    "low_battery": "¡BATERÍA BAJA! {detail} %: carga los mandos",
}
FOCUS_TEXT = {
    "on": "MyWhoosh en primer plano: los botones actúan",
    "off": "MyWhoosh no está en primer plano: los botones se ignoran",
}


def status_line(state: str, detail: str) -> str:
    if state == "focus":
        return FOCUS_TEXT[detail]
    return STATUS_TEXT.get(state, state).format(detail=detail)


async def run(args: argparse.Namespace) -> int:
    """Puente: eventos del mando -> teclas, con reconexión automática."""
    from .bridge import Bridge
    from .config import ConfigError, ensure_user_config, load_config
    from .output_keyboard import DryRunOutput, make_output

    path = args.config or ensure_user_config()
    try:
        config = load_config(path)
    except ConfigError as exc:
        print(f"Configuración no válida: {exc}")
        return 2
    printer = MonitorPrinter() if (args.dry_run or args.show_events) else None
    last = [""]

    def on_status(state: str, detail: str) -> None:
        if state == "searching" and last[0] == "searching":
            return  # no repetir la línea en cada ciclo de búsqueda
        last[0] = state
        if state == "battery" and printer is not None:
            return  # ya la muestra el impresor de eventos
        print(f"[{time.strftime('%H:%M:%S')}] {status_line(state, detail)}", flush=True)

    bridge = Bridge(
        config,
        DryRunOutput() if args.dry_run else make_output(args.method),
        on_status=on_status,
        on_message=printer.handle if printer else None,
        address=args.address,
        gate_focus=not args.dry_run and not args.any_window,
    )
    mode = "SIMULACIÓN, no se envían teclas" if args.dry_run else "enviando teclas"
    print(f"Configuración: {path} ({len(config.bindings)} controles). Modo: {mode}. Ctrl+C para salir.")
    await bridge.run()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m zwiftplay", description="Puente Zwift Ride/Play -> MyWhoosh")
    parser.add_argument("-v", "--verbose", action="store_true", help="logs de depuración")
    sub = parser.add_subparsers(dest="command", required=True)

    mon = sub.add_parser("monitor", help="muestra los eventos de los mandos en tiempo real")
    mon.add_argument("--replay", type=Path, help="reproducir una captura .jsonl en vez de conectar")
    mon.add_argument("--all", action="store_true", help="mostrar también reposo y mensajes desconocidos")
    mon.add_argument("--address", help="dirección Bluetooth del mando (por defecto, el primero compatible)")
    mon.add_argument("--scan-time", type=float, default=8.0)

    runp = sub.add_parser("run", help="puente: traduce los mandos a teclas según config.yaml")
    runp.add_argument("--config", type=Path, help="fichero de configuración (por defecto, el del usuario)")
    runp.add_argument("--any-window", action="store_true", help="actuar en cualquier ventana, no solo en MyWhoosh")
    runp.add_argument("--dry-run", action="store_true", help="no enviar teclas; mostrar qué se enviaría")
    runp.add_argument("--show-events", action="store_true", help="mostrar también los eventos del mando")
    runp.add_argument("--address", help="dirección Bluetooth del mando")

    runp.add_argument("--method", choices=["auto", "scancode", "vk"], default="auto",
                      help="cómo enviar las teclas (auto: scancode en Windows)")

    appp = sub.add_parser("app", help="aplicación de escritorio (ventana)")
    appp.add_argument("--minimized", action="store_true")

    kt = sub.add_parser("keytest", help="envía una tecla de prueba, sin mandos")
    kt.add_argument("key", nargs="?", default="k")
    kt.add_argument("--count", type=int, default=3)
    kt.add_argument("--delay", type=float, default=5.0, help="segundos de espera antes de empezar")
    kt.add_argument("--hold-ms", type=int, default=60)
    kt.add_argument("--method", choices=["auto", "scancode", "vk"], default="auto")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.command == "monitor":
        if args.replay:
            return replay(args.replay, args.all)
        try:
            return asyncio.run(monitor(args))
        except KeyboardInterrupt:
            return 130
    if args.command == "app":
        from .app import main as app_main

        return app_main(["--minimized"] if args.minimized else [])
    if args.command == "keytest":
        return keytest(args)
    if args.command == "run":
        try:
            return asyncio.run(run(args))
        except KeyboardInterrupt:
            return 130
    return 2


if __name__ == "__main__":
    sys.exit(main())
