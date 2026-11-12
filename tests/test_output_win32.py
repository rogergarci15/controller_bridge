import ctypes

from zwiftplay import output_win32 as w


def test_input_struct_matches_win64_layout():
    # sizeof(INPUT) en Windows de 64 bits es 40; SendInput rechaza otro tamaño.
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        assert ctypes.sizeof(w.INPUT) == 40
        assert w.INPUT.ki.offset == 8


def test_build_input_flags():
    down = w.build_input(0x25, extended=False, down=True)
    assert (down.type, down.ki.wVk, down.ki.wScan, down.ki.dwFlags) == (1, 0, 0x25, w.KEYEVENTF_SCANCODE)
    up = w.build_input(0x4B, extended=True, down=False)
    assert up.ki.dwFlags == w.KEYEVENTF_SCANCODE | w.KEYEVENTF_EXTENDEDKEY | w.KEYEVENTF_KEYUP


def test_special_keys_cover_config_names():
    from zwiftplay.output_keyboard import SPECIAL_KEYS
    assert SPECIAL_KEYS == set(w.VIRTUAL_KEYS)
    assert w.VIRTUAL_KEYS["f1"] == 0x70 and w.VIRTUAL_KEYS["f12"] == 0x7B
