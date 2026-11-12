"""Traduce eventos del mando en pulsaciones según la configuración.

Sin E/S ni relojes propios: el tiempo entra como parámetro y las teclas salen
por un objeto `Output`, así que todo se puede probar sin hardware ni teclado.

Modos de un botón:
  tap     al pulsar: tecla abajo y, `tap_ms` después, arriba. Una pulsación
          física = una pulsación de tecla, por mucho que se mantenga.
  hold    la tecla sigue pulsada mientras el botón (o la palanca) lo esté.
  repeat  como tap, y si se mantiene repite cada `repeat_interval` tras
          `repeat_delay`.
Pulsación larga (solo con tap): si se define `long_key`, la pulsación corta
se envía al SOLTAR, y al mantener `long_after` segundos se envía `long_key`.
"""

from __future__ import annotations

import heapq
import itertools
from dataclasses import dataclass
from typing import Callable, Protocol

from .protocol import AnalogEvent, ButtonEvent, Event


class Output(Protocol):
    def press(self, key: str) -> None: ...
    def release(self, key: str) -> None: ...


@dataclass(frozen=True)
class Binding:
    key: str
    mode: str = "tap"  # tap | hold | repeat
    tap_ms: int = 40
    repeat_delay: float = 0.4
    repeat_interval: float = 0.15
    long_key: str | None = None
    long_after: float = 0.6
    # Solo palancas: se activa al llegar a `threshold` y no se desactiva
    # hasta bajar de `release` (histéresis contra el ruido cerca del reposo).
    threshold: int = 50
    release: int = 30


class Mapper:
    def __init__(self, bindings: dict[str, Binding], output: Output):
        self.bindings = bindings
        self.output = output
        self._refs: dict[str, int] = {}  # tecla -> nº de motivos por los que está abajo
        self._timers: list[tuple[float, int, Callable[[float], None]]] = []
        self._seq = itertools.count()
        self._down_since: dict[str, float] = {}  # control -> instante de la pulsación
        self._generation: dict[str, int] = {}  # invalida temporizadores viejos de un control
        self._long_fired: set[str] = set()
        self._analog_active: set[str] = set()

    # --- teclas con recuento ------------------------------------------------
    def _key_down(self, key: str) -> None:
        count = self._refs.get(key, 0)
        if count:
            # Ya está abajo por otra pulsación aún sin terminar: soltar y
            # volver a pulsar para que el juego vea una pulsación nueva.
            self.output.release(key)
        self.output.press(key)
        self._refs[key] = count + 1

    def _key_up(self, key: str) -> None:
        count = self._refs.get(key, 0)
        if count <= 1:
            self._refs.pop(key, None)
            if count == 1:
                self.output.release(key)
        else:
            self._refs[key] = count - 1

    def _tap(self, key: str, now: float, tap_ms: int) -> None:
        self._key_down(key)
        self._at(now + tap_ms / 1000.0, lambda _t: self._key_up(key))

    # --- temporizadores -----------------------------------------------------
    def _at(self, when: float, action: Callable[[float], None]) -> None:
        heapq.heappush(self._timers, (when, next(self._seq), action))

    def next_deadline(self) -> float | None:
        return self._timers[0][0] if self._timers else None

    def tick(self, now: float) -> None:
        """Ejecuta los temporizadores vencidos. Llamar al llegar `next_deadline()`."""
        while self._timers and self._timers[0][0] <= now:
            when, _, action = heapq.heappop(self._timers)
            action(when)

    # --- eventos ------------------------------------------------------------
    def handle(self, event: Event, now: float) -> None:
        self.tick(now)
        binding = self.bindings.get(event.id)
        if binding is None:
            return
        if isinstance(event, ButtonEvent):
            self._control(event.id, binding, event.pressed, now)
        elif isinstance(event, AnalogEvent):
            active = event.id in self._analog_active
            if not active and event.value >= binding.threshold:
                self._analog_active.add(event.id)
                self._control(event.id, binding, True, now)
            elif active and event.value < binding.release:
                self._analog_active.discard(event.id)
                self._control(event.id, binding, False, now)

    def _control(self, control: str, b: Binding, pressed: bool, now: float) -> None:
        if pressed == (control in self._down_since):
            return  # sin cambio real
        generation = self._generation.get(control, 0) + 1
        self._generation[control] = generation

        def still_held() -> bool:
            return self._generation.get(control) == generation and control in self._down_since

        if pressed:
            self._down_since[control] = now
            if b.mode == "hold":
                self._key_down(b.key)
            elif b.long_key:
                def fire_long(when: float) -> None:
                    if still_held():
                        self._long_fired.add(control)
                        self._tap(b.long_key, when, b.tap_ms)
                self._at(now + b.long_after, fire_long)
            else:
                self._tap(b.key, now, b.tap_ms)
                if b.mode == "repeat":
                    def again(when: float) -> None:
                        if still_held():
                            self._tap(b.key, when, b.tap_ms)
                            self._at(when + b.repeat_interval, again)
                    self._at(now + b.repeat_delay, again)
        else:
            del self._down_since[control]
            if b.mode == "hold":
                self._key_up(b.key)
            elif b.long_key:
                if control in self._long_fired:
                    self._long_fired.discard(control)
                else:
                    self._tap(b.key, now, b.tap_ms)  # fue corta

    def reset(self) -> None:
        """Suelta todas las teclas y cancela todo (p. ej. al perder la conexión)."""
        for key in list(self._refs):
            self.output.release(key)
        self._refs.clear()
        self._timers.clear()
        self._down_since.clear()
        self._long_fired.clear()
        self._analog_active.clear()
