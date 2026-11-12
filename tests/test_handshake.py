import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from zwiftplay import handshake
from zwiftplay.constants import RIDE_ON


def test_plain_request_is_ascii_rideon():
    assert handshake.plain_request() == b"RideOn" == RIDE_ON


def test_public_key_bytes_matches_uncompressed_point_without_prefix():
    # Clave fija para que el test sea determinista.
    key = ec.derive_private_key(0x1234567890ABCDEF, ec.SECP256R1())
    from cryptography.hazmat.primitives import serialization as s
    point = key.public_key().public_bytes(s.Encoding.X962, s.PublicFormat.UncompressedPoint)
    assert point[0] == 0x04
    assert handshake.public_key_bytes(key) == point[1:]
    assert len(handshake.public_key_bytes(key)) == 64


def test_keyed_request_layout():
    key = handshake.generate_private_key()
    req = handshake.keyed_request(key)
    assert req[:6] == RIDE_ON and req[6:8] == b"\x01\x02" and len(req) == 72
    assert handshake.keyed_request(key, b"\x00\x09")[6:8] == b"\x00\x09"
    with pytest.raises(ValueError):
        handshake.keyed_request(key, b"\x00")


def test_parse_response_accepts_any_header():
    key = bytes(range(64))
    for header in (b"\x01\x04", b"\x01\x03", b"\x00\x09", b"\x01\x01"):
        assert handshake.parse_response(RIDE_ON + header) == (header, b"")
        assert handshake.parse_response(RIDE_ON + header + key) == (header, key)
    assert handshake.parse_response(RIDE_ON) == (b"", b"")
    assert handshake.parse_response(b"\x15") is None
    assert handshake.parse_response(RIDE_ON + b"\x01\x03" + b"\x00" * 10) is None
