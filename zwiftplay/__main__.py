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


async def run(args: argparse.Namespace) -> int:
    """Puente: eventos del mando -> teclas."""
    from bleak.exc import BleakError

    from .client import RideConnection, find_controller
    from .config import ConfigError, load_config
    from .mapper import Mapper
    from .output_keyboard import DryRunOutput, KeyboardOutput

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"Configuración no válida: {exc}")
        return 2
    output = DryRunOutput() if args.dry_run else KeyboardOutput()
    mapper = Mapper(config.bindings, output)
    printer = MonitorPrinter() if (args.dry_run or args.show_events) else None
    state = ControllerState()
    wake = asyncio.Event()

    def on_message(message: Message) -> None:
        # Camino crítico de latencia: se ejecuta en cuanto llega la notificación.
        if isinstance(message, Keypad):
            now = time.monotonic()
            for event in state.update(message):
                mapper.handle(event, now)
            wake.set()
        if printer is not None:
            printer.handle(message)

    async def timers() -> None:
        while True:
            deadline = mapper.next_deadline()
            timeout = None if deadline is None else max(0.0, deadline - time.monotonic())
            try:
                await asyncio.wait_for(wake.wait(), timeout)
            except asyncio.TimeoutError:
                pass
            wake.clear()
            mapper.tick(time.monotonic())

    print(f"Buscando el mando ({args.scan_time:.0f} s)… Zwift y Companion tienen que estar cerrados.")
    try:
        found = await find_controller(args.scan_time, args.address)
    except (BleakError, OSError) as exc:
        print(f"Error de Bluetooth: {exc}")
        return 2
    if found is None:
        print("No se ha encontrado ningún mando compatible. Prueba `python tools/scan.py`.")
        return 1
    connection = RideConnection(found, on_message)
    try:
        await connection.connect()
    except (BleakError, asyncio.TimeoutError, OSError, RuntimeError) as exc:
        print(f"No se pudo conectar a {found.label}: {exc}")
        return 1
    mode = "SIMULACIÓN, no se envían teclas" if args.dry_run else "enviando teclas a la ventana con el foco"
    print(f"Conectado a {found.label} (firmware {connection.firmware}). Modo: {mode}.")
    print(f"{len(config.bindings)} controles asignados. Ctrl+C para salir.\n")
    timer_task = asyncio.create_task(timers())
    try:
        await connection.disconnected.wait()
        print("\nEl mando se ha desconectado.")
    finally:
        timer_task.cancel()
        mapper.reset()  # que no quede ninguna tecla pulsada
        await connection.disconnect()
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
    runp.add_argument("--config", type=Path, default=Path("config.yaml"))
    runp.add_argument("--dry-run", action="store_true", help="no enviar teclas; mostrar qué se enviaría")
    runp.add_argument("--show-events", action="store_true", help="mostrar también los eventos del mando")
    runp.add_argument("--address", help="dirección Bluetooth del mando")
    runp.add_argument("--scan-time", type=float, default=8.0)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.command == "monitor":
        if args.replay:
            return replay(args.replay, args.all)
        try:
            return asyncio.run(monitor(args))
        except KeyboardInterrupt:
            return 130
    if args.command == "run":
        try:
            return asyncio.run(run(args))
        except KeyboardInterrupt:
            return 130
    return 2


if __name__ == "__main__":
    sys.exit(main())
