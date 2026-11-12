from pathlib import Path

import pytest

from zwiftplay import protocol as p
from zwiftplay.capture import read_capture
from zwiftplay.config import ConfigError, load_config, parse_config
from zwiftplay.mapper import Binding, Mapper

ROOT = Path(__file__).parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "ride_fw120_guided.jsonl"


class FakeOutput:
    def __init__(self):
        self.log = []
        self.down = set()

    def press(self, key):
        assert key not in self.down, f"{key} pulsada dos veces sin soltar"
        self.down.add(key)
        self.log.append(("down", key))

    def release(self, key):
        assert key in self.down, f"{key} soltada sin estar pulsada"
        self.down.discard(key)
        self.log.append(("up", key))


def btn(control, pressed):
    side, button = control.split(".")
    return p.ButtonEvent(side, button, pressed)


def paddle(side, value):
    return p.AnalogEvent(side, "paddle", value)


def make(**bindings):
    out = FakeOutput()
    return Mapper({k.replace("__", "."): v for k, v in bindings.items()}, out), out


def test_tap_is_one_keystroke_however_long_held():
    m, out = make(right__shift_upper=Binding("k"))
    m.handle(btn("right.shift_upper", True), 0.0)
    assert out.log == [("down", "k")] and m.next_deadline() == pytest.approx(0.06)
    m.tick(0.06)
    assert out.log == [("down", "k"), ("up", "k")]
    m.handle(btn("right.shift_upper", False), 3.0)  # soltar 3 s después: nada más
    m.tick(10.0)
    assert out.log == [("down", "k"), ("up", "k")] and m.next_deadline() is None


def test_two_buttons_same_key_overlapping_give_two_keystrokes():
    m, out = make(right__shift_upper=Binding("k"), right__shift_lower=Binding("k"))
    m.handle(btn("right.shift_upper", True), 0.0)
    m.handle(btn("right.shift_lower", True), 0.01)  # antes de que acabe el primer toque
    m.tick(1.0)
    assert out.log == [("down", "k"), ("up", "k"), ("down", "k"), ("up", "k")]


def test_hold_follows_button():
    m, out = make(left__up=Binding("up", mode="hold"))
    m.handle(btn("left.up", True), 0.0)
    m.tick(5.0)
    assert out.log == [("down", "up")]
    m.handle(btn("left.up", False), 5.0)
    assert out.log == [("down", "up"), ("up", "up")]


def test_repeat():
    m, out = make(left__up=Binding("x", mode="repeat", repeat_delay=0.4, repeat_interval=0.1))
    m.handle(btn("left.up", True), 0.0)
    for t in (0.06, 0.4, 0.46, 0.5, 0.56, 0.6, 0.66):
        m.tick(t)
    assert out.log.count(("down", "x")) == 4  # t=0, 0.4, 0.5, 0.6
    m.handle(btn("left.up", False), 0.67)
    m.tick(5.0)
    assert out.log.count(("down", "x")) == 4 and not out.down


def test_long_press_short_and_long():
    m, out = make(right__a=Binding("s", long_key="l", long_after=0.6))
    m.handle(btn("right.a", True), 0.0)
    m.tick(0.3)
    assert out.log == []  # la corta espera a soltar
    m.handle(btn("right.a", False), 0.3)
    m.tick(1.0)
    assert out.log == [("down", "s"), ("up", "s")]
    out.log.clear()
    m.handle(btn("right.a", True), 2.0)
    m.tick(2.6)
    m.handle(btn("right.a", False), 4.0)
    m.tick(5.0)
    assert out.log == [("down", "l"), ("up", "l")]


def test_stale_long_timer_ignored_after_quick_repress():
    m, out = make(right__a=Binding("s", long_key="l", long_after=0.6))
    m.handle(btn("right.a", True), 0.0)
    m.handle(btn("right.a", False), 0.1)
    m.handle(btn("right.a", True), 0.5)  # el temporizador de la 1ª vence en 0.6
    m.tick(0.7)
    assert ("down", "l") not in out.log
    m.tick(1.1)  # el de la 2ª vence en 1.1
    assert ("down", "l") in out.log


def test_paddle_threshold_and_hysteresis():
    m, out = make(left__paddle=Binding("a", mode="hold", threshold=50, release=30))
    for value in (5, 10, 49):
        m.handle(paddle("left", value), 0.0)
    assert out.log == []
    m.handle(paddle("left", 50), 0.1)
    assert out.log == [("down", "a")]
    for value in (100, 45, 31, 60, 30):  # oscila por encima de release: sigue pulsada
        m.handle(paddle("left", value), 0.2)
    assert out.log == [("down", "a")]
    m.handle(paddle("left", 29), 0.3)
    assert out.log == [("down", "a"), ("up", "a")]
    m.handle(paddle("left", -100), 0.4)  # negativo: no activa
    assert len(out.log) == 2


def test_reset_releases_everything():
    m, out = make(left__paddle=Binding("a", mode="hold"), right__shift_upper=Binding("k"))
    m.handle(paddle("left", 100), 0.0)
    m.handle(btn("right.shift_upper", True), 0.0)
    m.reset()
    assert not out.down and m.next_deadline() is None
    m.handle(paddle("left", 100), 1.0)  # tras el reset vuelve a funcionar
    assert out.down == {"a"}


def test_unbound_control_does_nothing():
    m, out = make()
    m.handle(btn("right.a", True), 0.0)
    assert out.log == [] and m.next_deadline() is None


# --- configuración ---------------------------------------------------------

def test_default_config_loads():
    cfg = load_config(ROOT / "config.yaml")
    assert cfg.bindings["right.shift_upper"] == Binding("k")
    assert cfg.bindings["left.shift_lower"].key == "i"
    assert cfg.bindings["left.paddle"] == Binding("a", mode="hold", threshold=50, release=30)
    assert cfg.bindings["right.paddle"].key == "d"
    assert cfg.bindings["right.b"].key == "enter" and cfg.bindings["left.powerup"].key == "space"
    assert cfg.low_battery == 15


def test_paddle_defaults_to_hold_and_numeric_keys_become_strings():
    cfg = parse_config({"mapping": {"left.paddle": "a", "right.a": 1, "right.b": None}})
    assert cfg.bindings["left.paddle"].mode == "hold"
    assert cfg.bindings["right.a"].key == "1" and "right.b" not in cfg.bindings


@pytest.mark.parametrize("mapping", [
    {"left.nope": "a"},
    {"right.a": {"mode": "tap"}},
    {"right.a": {"key": "a", "mode": "wat"}},
    {"right.a": {"key": "a", "threshold": 10}},
    {"right.a": {"key": "notakey"}},
    {"right.a": {"key": "a", "bogus": 1}},
    {"right.a": {"key": "a", "mode": "hold", "long_key": "b"}},
    {"left.paddle": {"key": "a", "threshold": 20, "release": 40}},
])
def test_bad_config_rejected(mapping):
    with pytest.raises(ConfigError):
        parse_config({"mapping": mapping})


# --- captura real con la configuración por defecto -------------------------

def test_real_capture_through_default_config():
    """Criterios de aceptación: 1 pulsación = 1 cambio; la dirección sigue a la palanca."""
    cfg = load_config(ROOT / "config.yaml")
    out = FakeOutput()
    mapper, state = Mapper(cfg.bindings, out), p.ControllerState()
    marks, current = {}, ""
    for rec in read_capture(FIXTURE):
        now = rec["mono"]
        mapper.tick(now)
        if rec["type"] == "label":
            if rec["phase"] == "start":
                current = rec["label"]
                marks[current] = len(out.log)
            else:
                marks[current] = out.log[marks[current]:]
        elif rec["type"] == "rx":
            msg = p.decode(bytes.fromhex(rec["hex"]))
            if isinstance(msg, p.Keypad):
                for event in state.update(msg):
                    mapper.handle(event, now)
    mapper.tick(1e12)
    assert not out.down

    assert marks["right_shift_1"] == [("down", "k"), ("up", "k")] * 3
    assert marks["right_shift_2"] == [("down", "k"), ("up", "k")] * 3
    assert marks["left_shift_1"] == [("down", "i"), ("up", "i")] * 3
    assert marks["left_shift_hold"] == [("down", "i"), ("up", "i")]  # mantener 3 s = 1 cambio
    assert marks["left_paddle"] == [("down", "a"), ("up", "a")] * 3
    assert marks["right_paddle"] == [("down", "d"), ("up", "d")] * 3
    assert marks["left_paddle_slow"] == [("down", "a"), ("up", "a")]
    assert marks["right_y"] == [("down", "tab"), ("up", "tab")] * 3
    for unbound in ("left_up", "right_a", "right_power_button", "idle"):
        assert marks[unbound] == []
