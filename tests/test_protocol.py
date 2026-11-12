from pathlib import Path

import pytest

from zwiftplay import protocol as p
from zwiftplay.capture import read_capture

FIXTURE = Path(__file__).parent / "fixtures" / "ride_fw120_guided.jsonl"
REST = "2308ffffffff0f1a04080010001a04080110001a04080210001a0408031000"


def h(text: str) -> bytes:
    return bytes.fromhex(text)


def events_by_label() -> dict[str, list[p.Event]]:
    """Reproduce la captura real y agrupa los eventos por paso del guion."""
    state, current, out = p.ControllerState(), "", {}
    for rec in read_capture(FIXTURE):
        if rec["type"] == "label":
            current = rec["label"] if rec["phase"] == "start" else ""
        elif rec["type"] == "rx":
            msg = p.decode(h(rec["hex"]))
            if isinstance(msg, p.Keypad):
                out.setdefault(current, []).extend(state.update(msg))
    return out


# --- mensajes sueltos (bytes tomados de la captura real) -------------------

def test_rest_frame():
    msg = p.decode(h(REST))
    assert msg == p.Keypad(pressed=frozenset(), analog={0: 0, 1: 0, 2: 0, 3: 0})


def test_idle_battery_handshake_unknown():
    assert p.decode(h("15")) == p.Idle()
    assert p.decode(h("19105e")) == p.Battery(level=94)
    assert p.decode(b"RideOn") == p.HandshakeAck(extra=b"")
    assert p.decode(b"RideOn\x01\x03") == p.HandshakeAck(extra=b"\x01\x03")
    log = p.decode(h("2a08031210120e080c100018c00722059ffdff9f1f"))
    assert isinstance(log, p.Unknown) and log.type == 0x2A


def test_two_buttons_at_once():
    msg = p.decode(h("2308ffddffff0f1a04080010001a04080110001a04080210001a0408031000"))
    assert msg.pressed == {("left", "shift_upper"), ("right", "shift_upper")}


def test_paddle_values():
    full_left = p.decode(h("2308ffffffff0f1a05080010c8011a04080110001a04080210001a0408031000"))
    assert full_left.analog == {0: 100, 1: 0, 2: 0, 3: 0}
    right = p.decode(h("2308ffffffff0f1a04080010001a04080110661a04080210001a0408031000"))
    assert right.analog[1] == 51
    negative = p.decode(h("2308ffffffff0f1a05080010c7011a04080110001a04080210001a0408031000"))
    assert negative.analog[0] == -100


def test_missing_bitmap_is_not_all_pressed():
    msg = p.decode(h("231a0408001000"))
    assert msg.pressed is None
    state = p.ControllerState()
    state.update(p.decode(h("2308fdffffff0f")))
    assert state.update(msg) == []  # no cambia nada
    assert state.pressed == {("left", "up")}


def test_unknown_bits_reported_not_mapped():
    msg = p.decode(h("2308fffffbff0f"))  # bit 0x10000 a 0
    assert msg.pressed == frozenset() and msg.unknown_bits == 0x10000


@pytest.mark.parametrize("bad", ["", "2308ff", "23", "1910", "230a05ff"])
def test_malformed(bad):
    if bad == "23":  # cuerpo vacío: válido, sin información
        assert p.decode(h(bad)) == p.Keypad(pressed=None)
        return
    with pytest.raises(p.ProtocolError):
        p.decode(h(bad))


# --- máquina de estados ----------------------------------------------------

def test_repeats_produce_no_events_and_switch_releases_first():
    state = p.ControllerState()
    up = p.decode(h("2308fdffffff0f"))
    down = p.decode(h("2308f7ffffff0f"))
    assert state.update(up) == [p.ButtonEvent("left", "up", True)]
    assert state.update(up) == []
    assert state.update(down) == [p.ButtonEvent("left", "up", False), p.ButtonEvent("left", "down", True)]
    assert state.release_all() == [p.ButtonEvent("left", "down", False)]
    assert state.release_all() == []


def test_release_all_zeroes_paddles():
    state = p.ControllerState()
    state.update(p.decode(h("2308ffffffff0f1a05080010c801")))
    assert state.release_all() == [p.AnalogEvent("left", "paddle", 0)]


# --- captura real completa -------------------------------------------------

BUTTON_STEPS = {
    "left_up": "left.up", "left_left": "left.left", "left_right": "left.right",
    "left_down": "left.down", "right_y": "right.y", "right_z": "right.z",
    "right_a": "right.a", "right_b": "right.b",
    "left_shift_1": "left.shift_upper", "left_shift_2": "left.shift_lower",
    "right_shift_1": "right.shift_upper", "right_shift_2": "right.shift_lower",
    "left_powerup": "left.powerup", "right_powerup": "right.powerup",
    "left_power_button": "left.power", "right_power_button": "right.power",
}


def test_every_frame_in_capture_decodes():
    types = set()
    for rec in read_capture(FIXTURE):
        if rec["type"] == "rx":
            msg = p.decode(h(rec["hex"]))
            types.add(type(msg).__name__ if not isinstance(msg, p.Unknown) else f"Unknown:{msg.type:#x}")
            if isinstance(msg, p.Keypad):
                assert msg.unknown_bits == 0 and set(msg.analog) == {0, 1, 2, 3}
                assert msg.analog[2] == msg.analog[3] == 0
    assert types == {"Keypad", "Battery", "Idle", "HandshakeAck", "Unknown:0x2a"}


@pytest.mark.parametrize("label,expected", sorted(BUTTON_STEPS.items()))
def test_each_step_is_exactly_three_presses_of_one_button(label, expected):
    events = events_by_label()[label]
    assert all(isinstance(e, p.ButtonEvent) for e in events)
    assert {e.id for e in events} == {expected}
    assert [e.pressed for e in events] == [True, False] * 3


def test_hold_is_one_press():
    events = events_by_label()["left_shift_hold"]
    assert events == [p.ButtonEvent("left", "shift_upper", True), p.ButtonEvent("left", "shift_upper", False)]


def test_idle_step_has_no_events():
    assert "idle" not in events_by_label()


@pytest.mark.parametrize("side", ["left", "right"])
def test_paddle_steps(side):
    by_label = events_by_label()
    events = by_label[f"{side}_paddle_slow"]
    assert all(isinstance(e, p.AnalogEvent) and e.id == f"{side}.paddle" for e in events)
    values = [e.value for e in events]
    assert max(values) == 100 and values[-1] == 0
    assert len({v for v in values if 0 < v < 100}) >= 5  # recorrido continuo, no todo/nada


def test_monitor_replay_runs(capsys):
    from zwiftplay.__main__ import main
    assert main(["monitor", "--replay", str(FIXTURE)]) == 0
    out = capsys.readouterr().out
    assert "handshake aceptado" in out and "batería 94 %" in out
    assert out.count("shift_upper  PULSADO") == 3 + 1 + 3 + 3 + 3  # pasos shift_1 x2, hold, dos a la vez x2
