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
