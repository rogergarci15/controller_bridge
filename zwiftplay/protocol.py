"""Decodificación de los mensajes del Zwift Ride (firmware 1.2.0) y modelo de eventos.

Formato de cada mensaje: [1 byte de tipo][cuerpo protobuf], sin cifrar.
Fuentes de cada dato en docs/PROTOCOL.md; todo lo de este módulo está además
verificado con una captura real (tests/fixtures/ride_fw120_guided.jsonl).

El protobuf se decodifica a mano (solo hacen falta varints y campos
delimitados por longitud): así no hay paso de generación de código y se
controla qué pasa cuando falta un campo. El esquema de referencia está en
proto/zwift_ride.proto.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, Union

from .constants import MSG_BATTERY, MSG_IDLE, MSG_RIDE_KEYPAD, RIDE_ON

MSG_LOG = 0x2A  # [BC] zp.pbenum.dart Opcode.LOG_DATA; visto en la captura


class ProtocolError(ValueError):
    """Mensaje mal formado."""


# --- protobuf mínimo ------------------------------------------------------

def _varint(buf: bytes, pos: int) -> tuple[int, int]:
    value = shift = 0
    while True:
        if pos >= len(buf):
            raise ProtocolError("varint truncado")
        byte = buf[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, pos
        shift += 7
        if shift > 63:
            raise ProtocolError("varint demasiado largo")


def _fields(buf: bytes) -> Iterator[tuple[int, int | bytes]]:
    """Recorre los campos de un mensaje protobuf: (número, valor)."""
    pos = 0
    while pos < len(buf):
        key, pos = _varint(buf, pos)
        number, wire = key >> 3, key & 7
        if wire == 0:  # varint
            value, pos = _varint(buf, pos)
            yield number, value
        elif wire == 2:  # delimitado por longitud
            length, pos = _varint(buf, pos)
            if pos + length > len(buf):
                raise ProtocolError("campo truncado")
            yield number, buf[pos:pos + length]
            pos += length
        else:
            raise ProtocolError(f"tipo de cable {wire} no esperado")


def _zigzag(n: int) -> int:
    return (n >> 1) ^ -(n & 1)


# --- botones --------------------------------------------------------------
# Bit del mapa -> (lado, botón). Lógica invertida: bit a 0 = pulsado.
# Tabla de [BC] zwift_ride.dart (enum RideButtonMask local), confirmada bit a
# bit con la captura real. La otra tabla de [BC] (zwift.pbenum.dart) NO
# coincide con el hardware a partir del botón Z.
BUTTON_BITS: dict[int, tuple[str, str]] = {
    0x0001: ("left", "left"),
    0x0002: ("left", "up"),
    0x0004: ("left", "right"),
    0x0008: ("left", "down"),
    0x0010: ("right", "a"),
    0x0020: ("right", "b"),
    0x0040: ("right", "y"),
    0x0080: ("right", "z"),
    0x0100: ("left", "shift_upper"),
    0x0200: ("left", "shift_lower"),
    0x0400: ("left", "powerup"),
    0x0800: ("left", "power"),
    0x1000: ("right", "shift_upper"),
    0x2000: ("right", "shift_lower"),
    0x4000: ("right", "powerup"),
    0x8000: ("right", "power"),
}
_KNOWN_MASK = sum(BUTTON_BITS)
_ALL_RELEASED = 0xFFFFFFFF

# Posición analógica -> (lado, eje). [BC] zwift.pbenum.dart RideAnalogLocation;
# [MK-R]. Las posiciones 2 y 3 llegan siempre a 0 en la captura.
ANALOG_LOCATIONS: dict[int, tuple[str, str]] = {
    0: ("left", "paddle"),
    1: ("right", "paddle"),
}


def button_id(side: str, button: str) -> str:
    """Identificador único usado en la configuración, p. ej. "left.shift_upper"."""
    return f"{side}.{button}"


ALL_BUTTON_IDS = [button_id(s, b) for s, b in BUTTON_BITS.values()]
ALL_ANALOG_IDS = [button_id(s, a) for s, a in ANALOG_LOCATIONS.values()]


# --- mensajes -------------------------------------------------------------

@dataclass(frozen=True)
class Keypad:
    """Estado completo del teclado (mensaje 0x23)."""

    pressed: frozenset[tuple[str, str]] | None  # None si el mensaje no trae mapa
    analog: dict[int, int] = field(default_factory=dict)  # posición -> valor -100..100
    unknown_bits: int = 0  # bits pulsados que no están en BUTTON_BITS


@dataclass(frozen=True)
class Battery:
    level: int  # porcentaje


@dataclass(frozen=True)
class Idle:
    pass


@dataclass(frozen=True)
class HandshakeAck:
    extra: bytes  # lo que venga tras "RideOn" (vacío en el Ride 1.2.0)


@dataclass(frozen=True)
class Unknown:
    type: int
    body: bytes


Message = Union[Keypad, Battery, Idle, HandshakeAck, Unknown]


def decode(data: bytes) -> Message:
    """Decodifica una notificación/indicación del servicio Zwift."""
    if not data:
        raise ProtocolError("mensaje vacío")
    if data.startswith(RIDE_ON):
        return HandshakeAck(extra=bytes(data[len(RIDE_ON):]))
    kind, body = data[0], bytes(data[1:])
    if kind == MSG_IDLE:
        return Idle()
    if kind == MSG_RIDE_KEYPAD:
        return _decode_keypad(body)
    if kind == MSG_BATTERY:
        # Nivel en el campo 2. [AJ] proto/BatteryStatus.kt; captura: 19 10 5e = 94 %.
        for number, value in _fields(body):
            if number == 2 and isinstance(value, int):
                return Battery(level=value)
        raise ProtocolError("mensaje de batería sin nivel")
    return Unknown(type=kind, body=body)


def _decode_keypad(body: bytes) -> Keypad:
    mask: int | None = None
    analog: dict[int, int] = {}
    for number, value in _fields(body):
        if number == 1 and isinstance(value, int):
            mask = value
        elif number == 3 and isinstance(value, bytes):
            # Submensaje {1: posición, 2: valor sint32}. En proto2 un campo
            # con valor 0 puede omitirse; la posición por defecto es 0.
            location, amount = 0, 0
            for sub_number, sub_value in _fields(value):
                if sub_number == 1 and isinstance(sub_value, int):
                    location = sub_value
                elif sub_number == 2 and isinstance(sub_value, int):
                    amount = _zigzag(sub_value)
            analog[location] = amount
    if mask is None:
        # Sin mapa de bits no se puede afirmar nada de los botones. NO se
        # interpreta como "todo pulsado" (0 = pulsado): sería una ráfaga de
        # pulsaciones fantasma.
        return Keypad(pressed=None, analog=analog)
    down = ~mask & _ALL_RELEASED
    pressed = frozenset(btn for bit, btn in BUTTON_BITS.items() if down & bit)
    return Keypad(pressed=pressed, analog=analog, unknown_bits=down & ~_KNOWN_MASK)


# --- eventos --------------------------------------------------------------

@dataclass(frozen=True)
class ButtonEvent:
    side: str  # "left" | "right"
    button: str  # "up", "a", "shift_upper", ...
    pressed: bool

    @property
    def id(self) -> str:
        return button_id(self.side, self.button)


@dataclass(frozen=True)
class AnalogEvent:
    side: str
    axis: str  # "paddle"
    value: int  # -100..100, 0 en reposo

    @property
    def id(self) -> str:
        return button_id(self.side, self.axis)


Event = Union[ButtonEvent, AnalogEvent]

_BUTTON_ORDER = {btn: i for i, btn in enumerate(BUTTON_BITS.values())}


class ControllerState:
    """Convierte estados sucesivos en eventos de cambio.

    El mando repite el mismo estado unas 10 veces por segundo mientras hay
    actividad; aquí solo salen los cambios, así que una pulsación física
    produce exactamente un evento de pulsar y uno de soltar.
    """

    def __init__(self) -> None:
        self.pressed: frozenset[tuple[str, str]] = frozenset()
        self.analog: dict[tuple[str, str], int] = {}

    def update(self, keypad: Keypad) -> list[Event]:
        events: list[Event] = []
        if keypad.pressed is not None:
            changed = sorted(keypad.pressed ^ self.pressed, key=_BUTTON_ORDER.__getitem__)
            # Primero lo que se suelta: al cambiar de un botón a otro en el
            # mismo mensaje no quedan dos teclas pulsadas a la vez.
            for side, button in changed:
                if (side, button) not in keypad.pressed:
                    events.append(ButtonEvent(side, button, False))
            for side, button in changed:
                if (side, button) in keypad.pressed:
                    events.append(ButtonEvent(side, button, True))
            self.pressed = keypad.pressed
        for location, value in sorted(keypad.analog.items()):
            target = ANALOG_LOCATIONS.get(location)
            if target is not None and self.analog.get(target, 0) != value:
                self.analog[target] = value
                events.append(AnalogEvent(target[0], target[1], value))
        return events

    def release_all(self) -> list[Event]:
        """Eventos para dejarlo todo suelto (p. ej. al perder la conexión)."""
        events: list[Event] = [
            ButtonEvent(side, button, False)
            for side, button in sorted(self.pressed, key=_BUTTON_ORDER.__getitem__)
        ]
        events += [AnalogEvent(side, axis, 0) for (side, axis), v in sorted(self.analog.items()) if v != 0]
        self.pressed = frozenset()
        self.analog = {}
        return events
