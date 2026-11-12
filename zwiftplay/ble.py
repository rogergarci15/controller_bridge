"""Ayudas BLE compartidas (bleak)."""

from __future__ import annotations

from dataclasses import dataclass

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from .discovery import ZwiftAdvert, classify


@dataclass
class FoundDevice:
    device: BLEDevice
    adv: AdvertisementData
    info: ZwiftAdvert

    @property
    def label(self) -> str:
        """Nombre corto para logs y capturas, p. ej. "play_left@AB:CD"."""
        return f"{self.info.kind}@{self.device.address[-5:]}"


async def scan_zwift(timeout: float = 8.0) -> list[FoundDevice]:
    """Escanea y devuelve los dispositivos que parecen de Zwift."""
    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    result: list[FoundDevice] = []
    for device, adv in found.values():
        info = classify(adv.local_name or device.name, adv.manufacturer_data, adv.service_uuids)
        if info is not None:
            result.append(FoundDevice(device, adv, info))
    result.sort(key=lambda f: (f.info.kind, f.device.address))
    return result


async def scan_first(kinds: tuple[str, ...], timeout: float = 5.0, address: str | None = None) -> FoundDevice | None:
    """Escanea y vuelve en cuanto aparece un dispositivo de alguno de esos tipos.

    A diferencia de `scan_zwift`, no espera el tiempo completo: sirve para
    reconectar rápido cuando el mando vuelve a encenderse.
    """
    import asyncio

    result: list[FoundDevice] = []
    seen = asyncio.Event()

    def on_detect(device: BLEDevice, adv: AdvertisementData) -> None:
        if seen.is_set():
            return
        if address and device.address.lower() != address.lower():
            return
        info = classify(adv.local_name or device.name, adv.manufacturer_data, adv.service_uuids)
        if info is not None and (info.kind in kinds or address):
            result.append(FoundDevice(device, adv, info))
            seen.set()

    async with BleakScanner(detection_callback=on_detect):
        try:
            await asyncio.wait_for(seen.wait(), timeout)
        except asyncio.TimeoutError:
            pass
    return result[0] if result else None
