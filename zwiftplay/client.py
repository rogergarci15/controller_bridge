"""Conexión BLE a un Zwift Ride: escaneo, suscripción, handshake y decodificación."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic

from . import constants as c
from . import handshake
from .ble import FoundDevice, scan_zwift
from .protocol import Message, ProtocolError, decode

log = logging.getLogger(__name__)

# Tipos de anuncio que hablan el protocolo del Ride por una sola conexión.
# El derecho ("ride_right") envía sus botones a través del izquierdo.
SUPPORTED_KINDS = ("ride_left", "play_fw2")
UNSUPPORTED_HINT = {
    "play_left": "Zwift Play con firmware 1.x: protocolo distinto, no implementado",
    "play_right": "Zwift Play con firmware 1.x: protocolo distinto, no implementado",
    "click": "Zwift Click: no implementado",
}

MessageHandler = Callable[[Message], None]


async def find_controller(timeout: float = 8.0, address: str | None = None) -> FoundDevice | None:
    """Busca el mando al que hay que conectarse (el izquierdo del Ride)."""
    found = await scan_zwift(timeout)
    for item in found:
        if address and item.device.address.lower() != address.lower():
            continue
        if item.info.kind in SUPPORTED_KINDS or address:
            return item
    for item in found:
        hint = UNSUPPORTED_HINT.get(item.info.kind)
        if hint:
            log.warning("%s: %s", item.label, hint)
    return None


class RideConnection:
    """Una conexión a un mando. Llama a `on_message` con cada mensaje decodificado.

    Los callbacks de bleak llegan en el bucle de asyncio, así que `on_message`
    se ejecuta en ese mismo hilo y debe ser rápido.
    """

    def __init__(self, found: FoundDevice, on_message: MessageHandler):
        self.found = found
        self.on_message = on_message
        self.disconnected = asyncio.Event()
        self.firmware: str | None = None
        self._client = BleakClient(found.device, disconnected_callback=self._on_disconnect, timeout=20.0)

    def _on_disconnect(self, _client: BleakClient) -> None:
        self.disconnected.set()

    def _on_data(self, _char: BleakGATTCharacteristic, data: bytearray) -> None:
        try:
            message = decode(bytes(data))
        except ProtocolError as exc:
            log.warning("mensaje no válido %s: %s", bytes(data).hex(), exc)
            return
        self.on_message(message)

    async def connect(self) -> None:
        client = self._client
        await client.connect()
        try:
            self.firmware = (await client.read_gatt_char(c.FIRMWARE_REVISION_CHAR_UUID)).decode("utf-8", "replace")
        except Exception:  # dato informativo: no impide funcionar
            self.firmware = None

        service = next((s for s in client.services if s.uuid.lower() in c.ZWIFT_SERVICE_UUIDS), None)
        if service is None:
            raise RuntimeError("el mando no expone el servicio Zwift (¿firmware bloqueado o muy antiguo?)")
        chars = {ch.uuid.lower(): ch for ch in service.characteristics}
        try:
            async_char, tx_char, rx_char = (
                chars[c.ASYNC_CHAR_UUID], chars[c.SYNC_TX_CHAR_UUID], chars[c.SYNC_RX_CHAR_UUID]
            )
        except KeyError as exc:
            raise RuntimeError(f"falta la característica {exc} en el servicio Zwift") from exc

        # Suscribirse antes del handshake: la respuesta llega por indicación.
        await client.start_notify(async_char, self._on_data)
        await client.start_notify(tx_char, self._on_data)
        await client.write_gatt_char(rx_char, handshake.plain_request(), response=False)

    async def disconnect(self) -> None:
        try:
            await self._client.disconnect()
        except Exception:
            pass

    @property
    def is_connected(self) -> bool:
        return self._client.is_connected
