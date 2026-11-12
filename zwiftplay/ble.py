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
