from zwiftplay.constants import ZWIFT_COMPANY_ID, ZWIFT_SERVICE_UUID
from zwiftplay.discovery import classify


def test_play_left_by_manufacturer_data():
    adv = classify("Zwift Play", {ZWIFT_COMPANY_ID: bytes([0x03, 0xAB, 0xCD])}, [ZWIFT_SERVICE_UUID])
    assert adv.kind == "play_left" and adv.side == "left"
    assert adv.matched_by == ("name", "manufacturer", "service")


def test_play_right_and_fw2():
    assert classify(None, {ZWIFT_COMPANY_ID: b"\x02"}, []).side == "right"
    fw2 = classify(None, {ZWIFT_COMPANY_ID: b"\x0e"}, [])
    assert fw2.kind == "play_fw2" and fw2.side is None


def test_name_only_is_unknown_kind():
    # En Windows el anuncio puede llegar sin datos de fabricante.
    adv = classify("Zwift Play", {}, [])
    assert adv.kind == "unknown" and adv.type_byte is None and adv.side is None


def test_service_uuid_case_insensitive():
    assert classify(None, None, [ZWIFT_SERVICE_UUID.upper()]).matched_by == ("service",)


def test_unknown_type_byte_and_empty_payload():
    assert classify(None, {ZWIFT_COMPANY_ID: b"\x7f"}, []).kind == "unknown"
    assert classify(None, {ZWIFT_COMPANY_ID: b""}, []).type_byte is None


def test_other_devices_ignored():
    assert classify("KICKR CORE", {0x004C: b"\x02"}, ["00001826-0000-1000-8000-00805f9b34fb"]) is None
    assert classify(None, None, None) is None
