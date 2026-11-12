"""Lectura y escritura de capturas BLE en JSON Lines.

Una línea por registro. Tipos de registro (campo "type"):
  meta    datos de la sesión o de un dispositivo (firmware, servicios...)
  tx      bytes escritos por nosotros en una característica
  rx      bytes recibidos por notificación/indicación
  label   inicio ("start") o fin ("end") de un paso etiquetado del guion
  event   conexión, desconexión, errores

Todos llevan "t" (hora Unix, s) y "mono" (reloj monótono, s) para poder medir
intervalos sin saltos de reloj.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Iterator, TextIO


class CaptureWriter:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh: TextIO = path.open("w", encoding="utf-8")
        self.counts: dict[str, int] = {}

    def write(self, type_: str, **fields: Any) -> dict[str, Any]:
        record = {"t": round(time.time(), 6), "mono": round(time.monotonic(), 6), "type": type_}
        record.update(fields)
        self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._fh.flush()  # que no se pierda nada si se corta con Ctrl+C
        self.counts[type_] = self.counts.get(type_, 0) + 1
        return record

    def rx(self, device: str, char: str, data: bytes) -> dict[str, Any]:
        return self.write("rx", device=device, char=char, hex=data.hex())

    def tx(self, device: str, char: str, data: bytes) -> dict[str, Any]:
        return self.write("tx", device=device, char=char, hex=data.hex())

    def label(self, label: str, phase: str, **extra: Any) -> dict[str, Any]:
        return self.write("label", label=label, phase=phase, **extra)

    def close(self) -> None:
        self._fh.close()

    def __enter__(self) -> "CaptureWriter":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def read_capture(path: Path) -> Iterator[dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def labelled_frames(path: Path) -> dict[str, list[dict[str, Any]]]:
    """Agrupa los registros "rx" por la etiqueta activa cuando llegaron.

    Los que llegan fuera de cualquier paso van a la clave "" (cadena vacía).
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    current = ""
    for rec in read_capture(path):
        if rec["type"] == "label":
            current = rec["label"] if rec["phase"] == "start" else ""
        elif rec["type"] == "rx":
            groups.setdefault(current, []).append(rec)
    return groups
