"""Escanea dispositivos Zwift y lista sus servicios y características.

Uso:
    python tools/scan.py              # escanea, conecta y lista servicios
    python tools/scan.py --no-connect # solo el anuncio
    python tools/scan.py --all        # muestra TODOS los dispositivos BLE vistos

Zwift y Zwift Companion tienen que estar cerrados: los mandos solo aceptan
una conexión a la vez.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError

from zwiftplay import constants as c
from zwiftplay.ble import FoundDevice, scan_zwift

READABLE_INFO = [
    ("fabricante", c.MANUFACTURER_NAME_CHAR_UUID),
    ("nº de serie", c.SERIAL_NUMBER_CHAR_UUID),
    ("hardware", c.HARDWARE_REVISION_CHAR_UUID),
    ("firmware", c.FIRMWARE_REVISION_CHAR_UUID),
]

KNOWN_CHARS = {
    c.ASYNC_CHAR_UUID: "ASYNC",
    c.SYNC_RX_CHAR_UUID: "SYNC_RX",
    c.SYNC_TX_CHAR_UUID: "SYNC_TX",
    c.UNKNOWN6_CHAR_UUID: "desconocida (…0006)",
}


def print_advert(found: FoundDevice) -> None:
    dev, adv, info = found.device, found.adv, found.info
    print(f"\n=== {adv.local_name or dev.name or '(sin nombre)'}  [{dev.address}]  RSSI {adv.rssi} dBm")
    print(f"    tipo: {info.kind}   reconocido por: {', '.join(info.matched_by)}")
    if adv.manufacturer_data:
        for company, payload in adv.manufacturer_data.items():
            print(f"    fabricante 0x{company:04X}: {payload.hex(' ')}")
    else:
        print("    (el anuncio no trae datos de fabricante)")
    for uuid in adv.service_uuids:
        print(f"    servicio anunciado: {uuid}")


async def print_gatt(found: FoundDevice) -> None:
    try:
        async with BleakClient(found.device, timeout=20.0) as client:
            for name, uuid in READABLE_INFO:
                try:
                    value = await client.read_gatt_char(uuid)
                    print(f"    {name}: {value.decode('utf-8', 'replace')}")
                except (BleakError, ValueError, KeyError) as exc:
                    print(f"    {name}: (no se pudo leer: {exc})")
            try:
                battery = await client.read_gatt_char(c.BATTERY_LEVEL_CHAR_UUID)
                print(f"    batería: {battery[0]} %")
            except (BleakError, ValueError, KeyError, IndexError) as exc:
                print(f"    batería: (no se pudo leer: {exc})")

            for service in client.services:
                mark = "  <-- servicio Zwift" if service.uuid.lower() in c.ZWIFT_SERVICE_UUIDS else ""
                print(f"    servicio {service.uuid}{mark}")
                for char in service.characteristics:
                    known = KNOWN_CHARS.get(char.uuid.lower(), "")
                    props = ", ".join(char.properties)
                    print(f"      car. {char.uuid}  [{props}]  {known}")
    except (BleakError, asyncio.TimeoutError, OSError) as exc:
        print(f"    !! No se pudo conectar: {exc}")
        print("       ¿Está Zwift o Zwift Companion abierto? ¿El mando sigue encendido?")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--timeout", type=float, default=8.0, help="segundos de escaneo (por defecto 8)")
    parser.add_argument("--no-connect", action="store_true", help="no conectar, mostrar solo el anuncio")
    parser.add_argument("--all", action="store_true", help="listar todos los dispositivos BLE vistos")
    args = parser.parse_args()

    print(f"Escaneando {args.timeout:.0f} s… (enciende los dos mandos)")
    try:
        if args.all:
            everything = await BleakScanner.discover(timeout=args.timeout, return_adv=True)
            for dev, adv in everything.values():
                mfr = " ".join(f"0x{k:04X}:{v.hex()}" for k, v in adv.manufacturer_data.items())
                print(f"  {dev.address}  {adv.rssi:>4} dBm  {adv.local_name or dev.name or '-'}  {mfr}")
            return 0
        found = await scan_zwift(args.timeout)
    except (BleakError, OSError) as exc:
        print(f"Error de Bluetooth: {exc}")
        print("Comprueba que el Bluetooth del PC está activado.")
        return 2

    if not found:
        print("No se ha encontrado ningún dispositivo Zwift.")
        print("Prueba: encender los mandos, cerrar Zwift/Companion, o `--all` para ver qué llega.")
        return 1

    for item in found:
        print_advert(item)
        if not args.no_connect:
            await print_gatt(item)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
