"""Identificación de dispositivos Zwift a partir de su anuncio BLE.

Lógica pura (sin bleak) para poder probarla sin hardware.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .constants import DEVICE_TYPES, ZWIFT_COMPANY_ID, ZWIFT_SERVICE_UUIDS


@dataclass(frozen=True)
class ZwiftAdvert:
    """Lo que se puede deducir de un anuncio."""

    kind: str  # "play_left", "play_right", "play_fw2", ..., o "unknown"
    type_byte: int | None  # primer byte de los datos de fabricante, si llegó
    matched_by: tuple[str, ...]  # "name", "manufacturer", "service"

    @property
    def side(self) -> str | None:
        if self.kind.endswith("_left"):
            return "left"
        if self.kind.endswith("_right"):
            return "right"
        return None


def classify(
    name: str | None,
    manufacturer_data: Mapping[int, bytes] | None,
    service_uuids: Iterable[str] | None,
) -> ZwiftAdvert | None:
    """Devuelve un ZwiftAdvert si el anuncio parece de un dispositivo Zwift.

    Se acepta cualquiera de los tres indicios porque en Windows el anuncio
    puede llegar sin datos de fabricante (comentario en [BC]
    bluetooth_device.dart: fromScanResult).
    """
    matched: list[str] = []
    if name and name.strip().lower().startswith("zwift"):
        matched.append("name")

    type_byte: int | None = None
    payload = (manufacturer_data or {}).get(ZWIFT_COMPANY_ID)
    if payload is not None:
        matched.append("manufacturer")
        if len(payload) >= 1:
            type_byte = payload[0]

    uuids = {u.lower() for u in (service_uuids or ())}
    if uuids.intersection(ZWIFT_SERVICE_UUIDS):
        matched.append("service")

    if not matched:
        return None
    kind = DEVICE_TYPES.get(type_byte, "unknown") if type_byte is not None else "unknown"
    return ZwiftAdvert(kind=kind, type_byte=type_byte, matched_by=tuple(matched))
