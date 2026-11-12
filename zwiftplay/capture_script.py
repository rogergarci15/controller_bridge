"""Guion de pulsaciones para etiquetar capturas (tools/sniff.py --mode guided).

Cada paso resuelve una duda concreta de docs/PROTOCOL.md §11.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Step:
    label: str  # identificador estable, se guarda en la captura
    text: str  # instrucción que ve el usuario
    seconds: float = 6.0


_PRESS = "pulsa y suelta 3 veces, despacio (1 por segundo)"

_LEFT = [
    ("up", "cruceta ARRIBA"),
    ("left", "cruceta IZQUIERDA"),
    ("right", "cruceta DERECHA"),
    ("down", "cruceta ABAJO"),
]
_RIGHT = [("y", "botón Y"), ("z", "botón Z"), ("a", "botón A"), ("b", "botón B")]


def steps_for_side(side: str) -> list[Step]:
    """Pasos para un mando ("left" o "right")."""
    if side not in ("left", "right"):
        raise ValueError(side)
    lado = "IZQUIERDO" if side == "left" else "DERECHO"
    steps = [Step(f"{side}_idle", f"Mando {lado}: NO toques nada.", 5.0)]
    for name, desc in _LEFT if side == "left" else _RIGHT:
        steps.append(Step(f"{side}_{name}", f"Mando {lado}: {desc} — {_PRESS}."))
    steps += [
        Step(
            f"{side}_side_button",
            f"Mando {lado}: botón LATERAL (el pequeño del borde, junto a la palanca) — {_PRESS}.",
        ),
        Step(
            f"{side}_power_button",
            f"Mando {lado}: botón de ENCENDIDO — 3 toques MUY CORTOS (si lo mantienes, se apaga).",
        ),
        Step(
            f"{side}_paddle_steer",
            f"Mando {lado}: palanca naranja, movimiento de GIRAR (empujarla de lado, hacia el "
            "centro del manillar) — a fondo y suelta, 3 veces.",
            8.0,
        ),
        Step(
            f"{side}_paddle_brake",
            f"Mando {lado}: palanca naranja, movimiento de FRENAR (tirar hacia ti, como una "
            "maneta de freno) — a fondo y suelta, 3 veces.",
            8.0,
        ),
        Step(
            f"{side}_paddle_steer_slow",
            f"Mando {lado}: palanca, movimiento de GIRAR, MUY DESPACIO: tarda unos 4 s en "
            "llegar al fondo y otros 4 s en volver. Una sola vez.",
            10.0,
        ),
        Step(
            f"{side}_paddle_steer_half",
            f"Mando {lado}: palanca, movimiento de GIRAR, hasta la MITAD del recorrido y "
            "mantenla ahí hasta que acabe el paso.",
            6.0,
        ),
        Step(
            f"{side}_shift_hold",
            f"Mando {lado}: botón LATERAL — mantenlo pulsado 3 segundos seguidos y suelta.",
            6.0,
        ),
    ]
    return steps


def guided_steps(sides: list[str]) -> list[Step]:
    steps: list[Step] = []
    for side in sides:
        steps += steps_for_side(side)
    return steps


# --- Zwift Ride (y Play con firmware 2.x) ---------------------------------
# Una sola conexión (mando izquierdo) transporta los botones de los dos lados.
# Lista de botones: [BC] zwift_ride.dart (availableButtons / RideButtonMask).
_RIDE_BUTTONS = [
    ("left_up", "IZQUIERDO: cruceta ARRIBA"),
    ("left_left", "IZQUIERDO: cruceta IZQUIERDA"),
    ("left_right", "IZQUIERDO: cruceta DERECHA"),
    ("left_down", "IZQUIERDO: cruceta ABAJO"),
    ("right_y", "DERECHO: botón Y"),
    ("right_z", "DERECHO: botón Z"),
    ("right_a", "DERECHO: botón A"),
    ("right_b", "DERECHO: botón B"),
    ("left_shift_1", "IZQUIERDO: botón de CAMBIO de ARRIBA (de los dos del borde, el superior)"),
    ("left_shift_2", "IZQUIERDO: botón de CAMBIO de ABAJO (de los dos del borde, el inferior)"),
    ("right_shift_1", "DERECHO: botón de CAMBIO de ARRIBA (de los dos del borde, el superior)"),
    ("right_shift_2", "DERECHO: botón de CAMBIO de ABAJO (de los dos del borde, el inferior)"),
    ("left_powerup", "IZQUIERDO: botón de POWER-UP (el suelto, si lo hay, en la parte baja)"),
    ("right_powerup", "DERECHO: botón de POWER-UP (el suelto, si lo hay, en la parte baja)"),
]


def ride_steps() -> list[Step]:
    steps = [Step("idle", "NO toques nada.", 5.0)]
    for label, desc in _RIDE_BUTTONS:
        steps.append(Step(label, f"Mando {desc} — {_PRESS}. Si ese botón no existe, no pulses nada."))
    for side, lado in (("left", "IZQUIERDO"), ("right", "DERECHO")):
        steps += [
            Step(f"{side}_power_button",
                 f"Mando {lado}: botón de ENCENDIDO — 3 toques MUY CORTOS (si lo mantienes, se apaga)."),
            Step(f"{side}_paddle", f"Mando {lado}: palanca naranja — a fondo y suelta, 3 veces.", 8.0),
            Step(f"{side}_paddle_slow",
                 f"Mando {lado}: palanca naranja MUY DESPACIO: unos 4 s hasta el fondo y 4 s de vuelta. Una vez.",
                 10.0),
            Step(f"{side}_paddle_half",
                 f"Mando {lado}: palanca naranja hasta la MITAD y mantenla hasta que acabe el paso."),
        ]
    steps += [
        Step("left_shift_hold", "Mando IZQUIERDO: un botón de CAMBIO — mantenlo 3 segundos y suelta."),
        Step("two_buttons", "Pulsa A LA VEZ un botón de cambio IZQUIERDO y uno DERECHO, 3 veces."),
        Step("other", "Cualquier botón o movimiento que NO haya salido en el guion (si lo hay). "
                      "Apunta cuál es para decírmelo.", 10.0),
    ]
    return steps
