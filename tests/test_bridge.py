from zwiftplay import protocol as p
from zwiftplay.bridge import Bridge
from zwiftplay.config import DEFAULT_CONFIG_PATH, ensure_user_config, load_config, parse_config

SHIFT_DOWN = bytes.fromhex("2308ffdfffff0f")  # bit 0x1000: cambio superior derecho pulsado
REST = bytes.fromhex("2308ffffffff0f")
PADDLE_LEFT_FULL = bytes.fromhex("2308ffffffff0f1a05080010c801")


class Out:
    def __init__(self):
        self.log = []

    def press(self, key): self.log.append(("down", key))
    def release(self, key): self.log.append(("up", key))
    def mouse_move(self, dx, dy): self.log.append(("move", dx, dy))
    def mouse_button(self, button, down): self.log.append(("mouse", button, down))


def make(focused=lambda: True, **kwargs):
    out, statuses = Out(), []
    bridge = Bridge(load_config(DEFAULT_CONFIG_PATH), out, on_status=lambda s, d: statuses.append((s, d)),
                    focus_check=lambda wanted: focused(), **kwargs)
    return bridge, out, statuses


def test_default_config_gates_on_mywhoosh():
    assert load_config(DEFAULT_CONFIG_PATH).only_when_focused == "MyWhoosh"


def test_events_reach_output_when_focused():
    bridge, out, statuses = make()
    bridge.handle_message(p.decode(SHIFT_DOWN))
    assert out.log == [("down", "k")] and ("focus", "on") in statuses


def test_nothing_sent_without_focus():
    bridge, out, statuses = make(focused=lambda: False)
    bridge.handle_message(p.decode(SHIFT_DOWN))
    bridge.handle_message(p.decode(REST))
    assert out.log == [] and statuses == [("focus", "off")]


def test_losing_focus_releases_held_keys():
    state = {"focused": True}
    bridge, out, statuses = make(focused=lambda: state["focused"])
    bridge.handle_message(p.decode(PADDLE_LEFT_FULL))
    assert out.log == [("down", "a")]
    state["focused"] = False
    bridge.handle_message(p.decode(SHIFT_DOWN))  # cualquier evento nuevo detecta el cambio
    assert out.log == [("down", "a"), ("up", "a")]
    assert statuses[-1] == ("focus", "off")


def test_gate_disabled_ignores_focus():
    seen = []
    out = Out()
    bridge = Bridge(load_config(DEFAULT_CONFIG_PATH), out, focus_check=lambda wanted: seen.append(wanted) or True,
                    gate_focus=False)
    bridge.handle_message(p.decode(SHIFT_DOWN))
    assert seen == [""] and out.log == [("down", "k")]


def test_battery_status_and_low_warning_once():
    bridge, out, statuses = make()
    for level in (94, 94, 15, 14, 13):
        bridge.handle_message(p.Battery(level))
    assert statuses == [("battery", "94"), ("battery", "15"), ("low_battery", "15"),
                        ("battery", "14"), ("battery", "13")]


def test_set_config_releases_and_swaps_mapping():
    bridge, out, _ = make()
    bridge.handle_message(p.decode(PADDLE_LEFT_FULL))
    bridge.set_config(parse_config({"mapping": {"right.shift_upper": "x"}}))
    assert out.log == [("down", "a"), ("up", "a")]
    bridge.handle_message(p.decode(SHIFT_DOWN))
    assert out.log[-1] == ("down", "x")


def test_user_config_created_from_default(tmp_path):
    path = ensure_user_config(tmp_path / "sub" / "config.yaml")
    assert path.read_bytes() == DEFAULT_CONFIG_PATH.read_bytes()
    path.write_text("mapping: {}\n", encoding="utf-8")
    assert ensure_user_config(path).read_text(encoding="utf-8") == "mapping: {}\n"  # no se pisa


def test_autostart_command_shape():
    from zwiftplay import autostart
    command = autostart.launch_command()
    assert command.startswith('"') and command.endswith("--minimized")
