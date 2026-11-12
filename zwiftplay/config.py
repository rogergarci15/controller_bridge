"""Carga y validación de config.yaml."""

from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import yaml

from .mapper import MOUSE_ACTIONS, Binding, MouseSettings
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
    mouse: MouseSettings = MouseSettings()
    only_when_focused: str = ""


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
        if not isinstance(spec, dict) or ("key" in spec) == ("mouse" in spec):
            raise ConfigError(f"`{control}`: hace falta una tecla (`key`) o una acción de ratón (`mouse`), no ambas")
        unknown = set(spec) - _BINDING_FIELDS
        if unknown:
            raise ConfigError(f"`{control}`: opciones desconocidas {sorted(unknown)}")
        if not is_analog and _ANALOG_ONLY & set(spec):
            raise ConfigError(f"`{control}`: threshold/release solo valen para las palancas")
        spec = dict(spec)
        if "mouse" in spec:
            if spec["mouse"] not in MOUSE_ACTIONS:
                raise ConfigError(f"`{control}`: `mouse` tiene que ser una de {', '.join(MOUSE_ACTIONS)}")
            if is_analog or set(spec) - {"mouse"}:
                raise ConfigError(f"`{control}`: una acción de ratón no admite más opciones ni vale para palancas")
            bindings[control] = Binding(mouse=spec["mouse"])
            continue
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
    raw_mouse = data.get("mouse") or {}
    try:
        mouse = MouseSettings(**{k: float(v) for k, v in raw_mouse.items()})
    except (TypeError, ValueError, AttributeError) as exc:
        raise ConfigError(f"`mouse`: opciones válidas start_speed, max_speed, accel_time, interval ({exc})") from exc
    if not (0 < mouse.start_speed <= mouse.max_speed and mouse.interval > 0 and mouse.accel_time >= 0):
        raise ConfigError("`mouse`: tiene que cumplirse 0 < start_speed <= max_speed, interval > 0")
    focus = data.get("only_when_focused") or ""
    if not isinstance(focus, str):
        raise ConfigError("`only_when_focused` tiene que ser un texto")
    return Config(bindings=bindings, low_battery=low_battery, mouse=mouse, only_when_focused=focus)


def load_config(path: Path) -> Config:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"no se puede leer {path}: {exc}") from exc
    try:
        return parse_config(yaml.safe_load(text))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: YAML no válido: {exc}") from exc


DEFAULT_CONFIG_PATH = Path(__file__).with_name("default_config.yaml")


def user_config_path() -> Path:
    """Fichero de configuración del usuario (se crea con los valores por defecto)."""
    import os
    import sys

    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "ZwiftRideBridge" / "config.yaml"


def ensure_user_config(path: Path | None = None) -> Path:
    """Devuelve la ruta de la configuración del usuario, creándola si no existe."""
    path = path or user_config_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(DEFAULT_CONFIG_PATH.read_bytes())
    return path
