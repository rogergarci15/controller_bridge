"""Captura las notificaciones/indicaciones de los Zwift Play en captures/*.jsonl.

Modos:
    python tools/sniff.py                    # guion guiado: te dice qué pulsar
    python tools/sniff.py --mode idle --duration 600   # 10 min sin tocar nada
    python tools/sniff.py --mode free        # captura libre hasta Ctrl+C

Handshake (--handshake):
    plain   escribe solo "RideOn"; el mando debería responder en claro (defecto)
    keyed   escribe "RideOn" + cabecera + clave pública; los datos irán cifrados.
            La clave privada de la sesión se guarda en la captura para poder
            descifrarla después.
    none    no escribe nada (para ver qué manda el mando sin handshake)

Zwift y Zwift Companion tienen que estar cerrados.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from datetime import datetime
from pathlib import Path

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.exc import BleakError

from zwiftplay import constants as c
from zwiftplay import handshake
from zwiftplay.ble import FoundDevice, scan_zwift
from zwiftplay.capture import CaptureWriter
from zwiftplay.capture_script import guided_steps

IDLE_HEX = bytes([c.MSG_IDLE]).hex()


class Session:
    """Una conexión a un mando, volcando todo lo que llega a la captura."""

    def __init__(self, found: FoundDevice, cap: CaptureWriter, args: argparse.Namespace):
        self.found = found
        self.cap = cap
        self.args = args
        self.name = found.label
        self.client = BleakClient(found.device, disconnected_callback=self._on_disconnect, timeout=20.0)
        self.rx_count = 0
        self.rx_non_idle = 0

    def _on_disconnect(self, _client: BleakClient) -> None:
        self.cap.write("event", device=self.name, event="disconnected")
        print(f"\n  !! {self.name}: DESCONECTADO")

    def _on_data(self, char: BleakGATTCharacteristic, data: bytearray) -> None:
        raw = bytes(data)
        self.cap.rx(self.name, char.uuid.lower(), raw)
        self.rx_count += 1
        if raw.hex() != IDLE_HEX:
            self.rx_non_idle += 1
        if self.args.verbose:
            print(f"    {self.name} {char.uuid[4:8]} <- {raw.hex(' ')}")

    async def start(self) -> None:
        dev, adv, info = self.found.device, self.found.adv, self.found.info
        await self.client.connect()
        self.cap.write("event", device=self.name, event="connected")

        meta: dict[str, object] = {
            "device": self.name,
            "address": dev.address,
            "name": adv.local_name or dev.name,
            "kind": info.kind,
            "type_byte": info.type_byte,
            "matched_by": list(info.matched_by),
            "manufacturer_data": {f"0x{k:04X}": v.hex() for k, v in adv.manufacturer_data.items()},
            "advertised_services": list(adv.service_uuids),
            "rssi": adv.rssi,
            "mtu": getattr(self.client, "mtu_size", None),
            "services": {
                s.uuid: {ch.uuid: list(ch.properties) for ch in s.characteristics}
                for s in self.client.services
            },
        }
        for key, uuid in (
            ("firmware", c.FIRMWARE_REVISION_CHAR_UUID),
            ("hardware", c.HARDWARE_REVISION_CHAR_UUID),
        ):
            try:
                meta[key] = (await self.client.read_gatt_char(uuid)).decode("utf-8", "replace")
            except (BleakError, ValueError, KeyError):
                meta[key] = None
        try:
            meta["battery"] = (await self.client.read_gatt_char(c.BATTERY_LEVEL_CHAR_UUID))[0]
        except (BleakError, ValueError, KeyError, IndexError):
            meta["battery"] = None
        self.cap.write("meta", **meta)
        print(f"  {self.name}: conectado (firmware {meta['firmware']}, batería {meta['battery']} %)")

        zwift_services = [s for s in self.client.services if s.uuid.lower() in c.ZWIFT_SERVICE_UUIDS]
        if not zwift_services:
            print(f"  !! {self.name}: no expone el servicio Zwift. Servicios: {list(meta['services'])}")
            return

        # Suscribirse ANTES del handshake: la respuesta llega por indicación.
        write_char: BleakGATTCharacteristic | None = None
        for service in zwift_services:
            for char in service.characteristics:
                if char.uuid.lower() == c.SYNC_RX_CHAR_UUID:
                    write_char = char
                if "notify" in char.properties or "indicate" in char.properties:
                    try:
                        await self.client.start_notify(char, self._on_data)
                    except BleakError as exc:
                        self.cap.write("event", device=self.name, event="subscribe_failed", char=char.uuid, error=str(exc))
                        print(f"  !! {self.name}: no se pudo suscribir a {char.uuid}: {exc}")
        try:
            await self.client.start_notify(c.BATTERY_LEVEL_CHAR_UUID, self._on_data)
        except (BleakError, ValueError, KeyError):
            pass  # no todos los firmwares notifican la batería

        if self.args.handshake == "none":
            return
        if write_char is None:
            print(f"  !! {self.name}: no se encontró SYNC_RX; no se puede hacer el handshake")
            return
        if self.args.handshake == "plain":
            request = handshake.plain_request()
        else:
            key = handshake.generate_private_key()
            request = handshake.keyed_request(key, bytes.fromhex(self.args.key_header))
            # Clave efímera de esta sesión: hace falta para descifrar la captura.
            self.cap.write(
                "meta",
                device=self.name,
                session_private_key=f"{key.private_numbers().private_value:064x}",
                session_public_key=handshake.public_key_bytes(key).hex(),
            )
        # Escritura sin respuesta, como [BC] zwift_device.dart setupHandshake.
        self.cap.tx(self.name, write_char.uuid.lower(), request)  # antes de escribir: orden real
        await self.client.write_gatt_char(write_char, request, response=False)

    async def stop(self) -> None:
        try:
            await self.client.disconnect()
        except (BleakError, OSError, asyncio.TimeoutError):
            pass


async def countdown(seconds: float) -> None:
    end = time.monotonic() + seconds
    while (left := end - time.monotonic()) > 0:
        print(f"\r      quedan {left:4.1f} s ", end="", flush=True)
        await asyncio.sleep(min(0.2, left))
    print("\r" + " " * 30 + "\r", end="", flush=True)


async def ask_enter(prompt: str) -> None:
    await asyncio.to_thread(input, prompt)


async def run_guided(sessions: list[Session], cap: CaptureWriter, sides: list[str]) -> None:
    steps = guided_steps(sides)
    print(f"\nGuion de {len(steps)} pasos. En cada uno: lee la instrucción, pulsa Enter y hazlo")
    print("mientras corre la cuenta atrás. Si te equivocas, sigue; anótalo y me lo dices.\n")
    for index, step in enumerate(steps, 1):
        await ask_enter(f"[{index}/{len(steps)}] {step.text}\n      Enter para empezar… ")
        before = sum(s.rx_non_idle for s in sessions)
        cap.label(step.label, "start", text=step.text)
        await countdown(step.seconds)
        cap.label(step.label, "end")
        got = sum(s.rx_non_idle for s in sessions) - before
        print(f"      -> {got} mensajes (sin contar los de reposo)" + ("   !! NINGUNO" if got == 0 and "idle" not in step.label else ""))


async def run_timed(sessions: list[Session], cap: CaptureWriter, label: str, duration: float | None) -> None:
    cap.label(label, "start")
    start = time.monotonic()
    try:
        while duration is None or time.monotonic() - start < duration:
            await asyncio.sleep(10 if duration is None or duration > 30 else 1)
            status = "  ".join(
                f"{s.name}: {'ok' if s.client.is_connected else 'DESCONECTADO'} {s.rx_count} msgs" for s in sessions
            )
            print(f"  [{time.monotonic() - start:5.0f} s] {status}")
    finally:
        cap.label(label, "end")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=["guided", "idle", "free"], default="guided")
    parser.add_argument("--duration", type=float, default=600.0, help="segundos del modo idle (por defecto 600)")
    parser.add_argument("--handshake", choices=["plain", "keyed", "none"], default="plain")
    parser.add_argument(
        "--key-header",
        default=c.KEYED_REQUEST_HEADER_CAPTURED.hex(),
        help="2 bytes en hex tras 'RideOn' en modo keyed: 0102 (captura real, defecto) o 0009",
    )
    parser.add_argument("--address", action="append", help="conectar solo a esta dirección (repetible)")
    parser.add_argument("--scan-time", type=float, default=8.0)
    parser.add_argument("--out", type=Path, default=Path("captures"))
    parser.add_argument("--note", default="", help="texto libre que se guarda en la captura")
    parser.add_argument("-v", "--verbose", action="store_true", help="imprimir cada mensaje en hex")
    args = parser.parse_args()
    if len(bytes.fromhex(args.key_header)) != 2:
        parser.error("--key-header tiene que ser de 2 bytes, p. ej. 0102")

    print(f"Escaneando {args.scan_time:.0f} s… (enciende los dos mandos)")
    try:
        found = await scan_zwift(args.scan_time)
    except (BleakError, OSError) as exc:
        print(f"Error de Bluetooth: {exc}")
        return 2
    if args.address:
        wanted = {a.lower() for a in args.address}
        found = [f for f in found if f.device.address.lower() in wanted]
    if not found:
        print("No se ha encontrado ningún dispositivo Zwift. Prueba `python tools/scan.py --all`.")
        return 1

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = args.out / f"{stamp}_{args.mode}_{args.handshake}.jsonl"
    with CaptureWriter(path) as cap:
        cap.write(
            "meta",
            tool="sniff",
            mode=args.mode,
            handshake=args.handshake,
            key_header=args.key_header if args.handshake == "keyed" else None,
            platform=sys.platform,
            note=args.note,
        )
        sessions = [Session(f, cap, args) for f in found]
        try:
            for session in sessions:
                try:
                    await session.start()
                except (BleakError, asyncio.TimeoutError, OSError) as exc:
                    cap.write("event", device=session.name, event="connect_failed", error=str(exc))
                    print(f"  !! {session.name}: no se pudo conectar: {exc}")
            active = [s for s in sessions if s.client.is_connected]
            if not active:
                print("No se pudo conectar a ningún mando. ¿Zwift o Companion abiertos?")
                return 1

            await asyncio.sleep(2.0)  # margen para la respuesta al handshake
            for s in active:
                print(f"  {s.name}: {s.rx_count} mensajes en los 2 s tras el handshake")

            if args.mode == "guided":
                sides = sorted({s.found.info.side for s in active if s.found.info.side})
                if not sides or any(s.found.info.side is None for s in active):
                    sides = ["left", "right"]  # sin datos de fabricante no sabemos el lado
                await run_guided(active, cap, sides)
            elif args.mode == "idle":
                print(f"\nModo reposo: NO toques los mandos durante {args.duration:.0f} s.")
                await run_timed(active, cap, "idle_long", args.duration)
            else:
                print("\nCaptura libre. Ctrl+C para terminar.")
                await run_timed(active, cap, "free", None)
        except (KeyboardInterrupt, asyncio.CancelledError):
            print("\nInterrumpido.")
        finally:
            for session in sessions:
                await session.stop()
        print(f"\nCaptura guardada en {path}  ({cap.counts.get('rx', 0)} mensajes recibidos)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(130)
