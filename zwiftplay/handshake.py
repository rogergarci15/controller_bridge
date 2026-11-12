"""Construcción de los mensajes de handshake (docs/PROTOCOL.md §3)."""

from __future__ import annotations

from cryptography.hazmat.primitives.asymmetric import ec

from .constants import KEYED_REQUEST_HEADER_CAPTURED, PUBLIC_KEY_LENGTH, RIDE_ON


def plain_request() -> bytes:
    """Handshake sin cifrar: solo "RideOn".

    Fuente: [BC] zwift_device.dart setupHandshake; [AJ] AbstractZapDevice
    buildHandshakeStart (rama sin cifrado).
    """
    return RIDE_ON


def generate_private_key() -> ec.EllipticCurvePrivateKey:
    # Curva secp256r1 (P-256). Fuente: [AJ] crypto/LocalKeyProvider.kt; [MK-P]
    return ec.generate_private_key(ec.SECP256R1())


def public_key_bytes(key: ec.EllipticCurvePrivateKey | ec.EllipticCurvePublicKey) -> bytes:
    """Clave pública como X || Y (32 + 32 bytes), sin el prefijo 0x04.

    Fuente: [AJ] crypto/EncryptionUtils.kt publicKeyToByteArray; [MK-P].
    """
    public = key.public_key() if isinstance(key, ec.EllipticCurvePrivateKey) else key
    numbers = public.public_numbers()
    return numbers.x.to_bytes(32, "big") + numbers.y.to_bytes(32, "big")


def keyed_request(
    key: ec.EllipticCurvePrivateKey, header: bytes = KEYED_REQUEST_HEADER_CAPTURED
) -> bytes:
    """Handshake con clave: "RideOn" + 2 bytes de cabecera + clave pública."""
    if len(header) != 2:
        raise ValueError("la cabecera del handshake tiene que ser de 2 bytes")
    return RIDE_ON + header + public_key_bytes(key)


def parse_response(data: bytes) -> tuple[bytes, bytes] | None:
    """Interpreta la respuesta del mando al handshake.

    Devuelve (cabecera, clave_pública) o None si no es una respuesta de
    handshake. La clave va vacía en modo sin cifrar. No se exige un valor
    concreto de cabecera porque las fuentes no coinciden (PROTOCOL.md §3.2).
    """
    if not data.startswith(RIDE_ON):
        return None
    rest = data[len(RIDE_ON):]
    header, key = rest[:2], rest[2:]
    if len(key) not in (0, PUBLIC_KEY_LENGTH):
        return None
    return header, key
