"""El puente completo: busca el mando, conecta, traduce y se reconecta solo.

Lo usan tanto la línea de órdenes (`python -m zwiftplay run`) como la
aplicación de escritorio. Informa de su estado por un callback para que
quien lo use decida cómo mostrarlo.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable

from .config import Config
from .focus import is_focused
from .mapper import Mapper, Output
from .protocol import Battery, ControllerState, Keypad, Message

log = logging.getLogger(__name__)

# Estados que se notifican: (estado, detalle)
#   searching      buscando el mando
#   connecting     encontrado, conectando
#   connected      conectado (detalle: firmware)
#   disconnected   conexión perdida (detalle: motivo)
#   error          fallo de Bluetooth (detalle: mensaje)
#   battery        nivel de batería (detalle: "87")
#   low_battery    batería por debajo del umbral (detalle: nivel)
#   focus          "on"/"off": si los botones están actuando o no
StatusHandler = Callable[[str, str], None]

SCAN_TIMEOUT = 5.0
# El mando envía un mensaje de reposo cada segundo. Si pasa este tiempo sin
# recibir nada, la conexión está muerta aunque el sistema no lo haya notado.
SILENCE_TIMEOUT = 6.0
RETRY_DELAYS = (0.5, 1.0, 2.0, 4.0, 8.0)  # backoff entre intentos fallidos de conexión


class Bridge:
    def __init__(
        self,
        config: Config,
        output: Output,
        on_status: StatusHandler | None = None,
        on_message: Callable[[Message], None] | None = None,
        address: str | None = None,
        focus_check: Callable[[str], bool] = is_focused,
        gate_focus: bool = True,
    ):
        self.output = output
        self.on_status = on_status or (lambda state, detail: None)
        self.on_message_extra = on_message
        self.address = address
        self._focus_check = focus_check
        self._gate_focus = gate_focus
        self._state = ControllerState()
        self._wake = asyncio.Event()
        self._last_rx = 0.0
        self._battery: int | None = None
        self._battery_warned = False
        self._focused: bool | None = None
        self.set_config(config)

    def set_config(self, config: Config) -> None:
        """Aplica una configuración nueva (también en caliente)."""
        old = getattr(self, "mapper", None)
        if old is not None:
            old.reset()
        self.config = config
        self.mapper = Mapper(config.bindings, self.output, config.mouse)
        self._battery_warned = False
        self._wake.set()

    # --- mensajes del mando (camino crítico de latencia) --------------------
    def handle_message(self, message: Message) -> None:
        self._last_rx = time.monotonic()
        if isinstance(message, Keypad):
            events = self._state.update(message)
            if events:
                if self._update_focus():
                    now = self._last_rx
                    for event in events:
                        self.mapper.handle(event, now)
                    self._wake.set()
        elif isinstance(message, Battery):
            self._handle_battery(message.level)
        if self.on_message_extra is not None:
            self.on_message_extra(message)

    def _update_focus(self) -> bool:
        wanted = self.config.only_when_focused if self._gate_focus else ""
        focused = self._focus_check(wanted)
        if focused != self._focused:
            if self._focused and not focused:
                self.mapper.reset()  # que no quede nada pulsado en la otra ventana
            self._focused = focused
            self.on_status("focus", "on" if focused else "off")
        return focused

    def _handle_battery(self, level: int) -> None:
        if level != self._battery:
            self._battery = level
            self.on_status("battery", str(level))
        if level <= self.config.low_battery and not self._battery_warned:
            self._battery_warned = True
            self.on_status("low_battery", str(level))
        elif level > self.config.low_battery + 5:
            self._battery_warned = False

    # --- bucles --------------------------------------------------------------
    async def _timers(self) -> None:
        while True:
            deadline = self.mapper.next_deadline()
            timeout = None if deadline is None else max(0.0, deadline - time.monotonic())
            try:
                await asyncio.wait_for(self._wake.wait(), timeout)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
            if self.mapper.next_deadline() is not None and not self._update_focus():
                self.mapper.reset()  # sin foco: nada pendiente ni pulsado
                continue
            self.mapper.tick(time.monotonic())

    async def _session(self, connection) -> str:
        """Mantiene una conexión hasta que se pierde. Devuelve el motivo."""
        self._last_rx = time.monotonic()
        while True:
            try:
                await asyncio.wait_for(connection.disconnected.wait(), 1.0)
                return "el mando se ha desconectado"
            except asyncio.TimeoutError:
                if time.monotonic() - self._last_rx > SILENCE_TIMEOUT:
                    return "el mando ha dejado de responder"

    async def run(self) -> None:
        """Bucle principal: no termina hasta que se cancela la tarea."""
        from bleak.exc import BleakError

        from .ble import scan_first
        from .client import SUPPORTED_KINDS, RideConnection

        timers = asyncio.create_task(self._timers())
        failures = 0
        try:
            while True:
                self.on_status("searching", "")
                try:
                    found = await scan_first(SUPPORTED_KINDS, SCAN_TIMEOUT, self.address)
                except (BleakError, OSError) as exc:
                    self.on_status("error", f"Bluetooth no disponible: {exc}")
                    await asyncio.sleep(5.0)
                    continue
                if found is None:
                    continue  # seguir buscando: el mando estará apagado

                self.on_status("connecting", found.label)
                connection = RideConnection(found, self.handle_message)
                try:
                    await connection.connect()
                except (BleakError, asyncio.TimeoutError, OSError, RuntimeError) as exc:
                    await connection.disconnect()
                    delay = RETRY_DELAYS[min(failures, len(RETRY_DELAYS) - 1)]
                    failures += 1
                    self.on_status("error", f"no se pudo conectar ({exc}); reintento en {delay:.0f} s")
                    await asyncio.sleep(delay)
                    continue

                failures = 0
                self._state = ControllerState()
                self._focused = None
                self.on_status("connected", connection.firmware or "")
                try:
                    reason = await self._session(connection)
                finally:
                    self.mapper.reset()  # que no quede ninguna tecla pulsada
                    await connection.disconnect()
                self._battery = None
                self.on_status("disconnected", reason)
        finally:
            timers.cancel()
            self.mapper.reset()
