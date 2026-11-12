"""Carga y validación de config.yaml."""

from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import yaml

from .mapper import Binding
from .output_keyboard import validate_key
from .protocol import ALL_ANALOG_IDS, ALL_BUTTON_IDS

MODES = ("tap", "hold", "repeat")
_BINDING_FIELDS = {f.name for f in fields(Binding)}
_ANALOG_ONLY = {"threshold", "release"}


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Config:
    bindings: dict[str, Binding]
    low_battery: int = 15


def parse_config(data: Any) -> Config:
    if not isinstance(data, dict):
        raise ConfigError("el fichero de configuración tiene que ser un mapa YAML")
    raw = data.get("mapping") or {}
    if not isinstance(raw, dict):
        raise ConfigError("`mapping` tiene que ser un mapa de control -> acción")

    bindings: dict[str, Binding] = {}
    for control, spec in raw.items():
        if spec is None:
            continue  # control sin asignar
        is_analog = control in ALL_ANALOG_IDS
        if not is_analog and control not in ALL_BUTTON_IDS:
            valid = ", ".join(ALL_BUTTON_IDS + ALL_ANALOG_IDS)
            raise ConfigError(f"control desconocido `{control}`. Válidos: {valid}")
        if isinstance(spec, (str, int)) and not isinstance(spec, bool):  # forma corta; `1` en YAML es un entero
            spec = {"key": spec}
        if not isinstance(spec, dict) or "key" not in spec:
            raise ConfigError(f"`{control}`: hace falta una tecla (`key`)")
        unknown = set(spec) - _BINDING_FIELDS
        if unknown:
            raise ConfigError(f"`{control}`: opciones desconocidas {sorted(unknown)}")
        if not is_analog and _ANALOG_ONLY & set(spec):
            raise ConfigError(f"`{control}`: threshold/release solo valen para las palancas")
        spec = dict(spec)
        spec["key"] = str(spec["key"])
        if spec.get("long_key") is not None:
            spec["long_key"] = str(spec["long_key"])
        # Una palanca mantiene la tecla por defecto; un botón da un toque.
        spec.setdefault("mode", "hold" if is_analog else "tap")
        binding = Binding(**spec)
        for key in filter(None, (binding.key, binding.long_key)):
            try:
                validate_key(key)
            except ValueError as exc:
                raise ConfigError(f"`{control}`: {exc}") from exc
        if binding.mode not in MODES:
            raise ConfigError(f"`{control}`: modo `{binding.mode}` no válido ({', '.join(MODES)})")
        if binding.long_key and binding.mode != "tap":
            raise ConfigError(f"`{control}`: `long_key` solo se puede usar con mode: tap")
        if not 0 <= binding.release <= binding.threshold <= 100:
            raise ConfigError(f"`{control}`: tiene que cumplirse 0 <= release <= threshold <= 100")
        if binding.tap_ms <= 0 or binding.repeat_interval <= 0 or binding.repeat_delay < 0 or binding.long_after <= 0:
            raise ConfigError(f"`{control}`: los tiempos tienen que ser positivos")
        bindings[control] = binding

    low_battery = data.get("low_battery", 15)
    if not isinstance(low_battery, int) or not 0 <= low_battery <= 100:
        raise ConfigError("`low_battery` tiene que ser un entero entre 0 y 100")
    return Config(bindings=bindings, low_battery=low_battery)


def load_config(path: Path) -> Config:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"no se puede leer {path}: {exc}") from exc
    try:
        return parse_config(yaml.safe_load(text))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: YAML no válido: {exc}") from exc
