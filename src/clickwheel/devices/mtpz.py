"""The MTPZ handshake that unlocks writing to a Zune.

A Python port of libmtp's mtpz.c (Sajid Anwar, LGPL-2.1+). Its hand-rolled
crypto is standard underneath, so this uses library primitives instead:
RSA-PSS/OAEP over SHA-1 (done by hand: raw RSA with MGF1), AES-128-CBC and
AES-CMAC.

The keys are Microsoft's and are not shipped: like libmtp, this reads them
from ``~/.mtpz-data`` (five hex lines: public exponent, an encryption key the
handshake doesn't use, modulus, private key, certificates).
"""

from __future__ import annotations

import hashlib
import os
import struct
from dataclasses import dataclass
from pathlib import Path

from Crypto.Cipher import AES
from Crypto.Hash import CMAC

from . import mtp

KEY_FILE = Path.home() / ".mtpz-data"

# Operations / properties
END_TRUSTED_APP_SESSION = 0x9216
SEND_APP_REQUEST = 0x9212
GET_APP_RESPONSE = 0x9213
ENABLE_TRUSTED_FILE_OPERATIONS = 0x9214
SESSION_INITIATOR_INFO = 0xD406

# The Zune HD rejects the handshake's confirmation step under any other
# session-initiator name (tested on firmware 4.5), so this must stay libmtp's.
INITIATOR = "libmtp/Sajid Anwar - MTPZClassDriver"


class MtpzError(mtp.MtpError):
    pass


@dataclass(frozen=True)
class Keys:
    public_exponent: int
    modulus: int
    private_key: int
    certificates: bytes


def load_keys(path: Path = KEY_FILE) -> Keys | None:
    """The MTPZ keys, or None if the file is missing or malformed."""
    try:
        lines = [line.strip() for line in path.read_text().splitlines()]
        exponent, _encryption_key, modulus, private_key, certificates = lines[:5]
        return Keys(int(exponent, 16), int(modulus, 16), int(private_key, 16), bytes.fromhex(certificates))
    except (OSError, ValueError):
        return None


def mgf1(seed: bytes, length: int) -> bytes:
    out = b"".join(hashlib.sha1(seed + struct.pack(">I", i)).digest() for i in range(length // 20 + 1))
    return out[:length]


def _xor(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def _rsa_private(keys: Keys, block: bytes) -> bytes:
    return pow(int.from_bytes(block, "big"), keys.private_key, keys.modulus).to_bytes(128, "big")


def certificate_message(keys: Keys, random: bytes) -> bytes:
    """The application's certificate plus ``random``, signed RSA-PSS/SHA-1 with no salt."""
    body = b"\x02\x01\x01" + struct.pack(">I", len(keys.certificates)) + keys.certificates \
        + b"\x00\x10" + random
    m_hash = hashlib.sha1(body[2:]).digest()  # the signature covers all but the first two bytes
    h = hashlib.sha1(bytes(8) + m_hash).digest()
    db = bytearray(_xor(bytes(106) + b"\x01", mgf1(h, 107)))
    db[0] &= 0x7F
    signature = _rsa_private(keys, bytes(db) + h + b"\xbc")
    return body + b"\x01\x00\x80" + signature


def session_hash(keys: Keys, response: bytes, random: bytes) -> bytes:
    """Unwrap the device's reply to the certificate message; returns the 20-byte session hash."""
    if response[:2] != b"\x02\x02" or response[3] != 0x80:
        raise MtpzError("Unexpected handshake reply from the device")
    decrypted = _rsa_private(keys, response[4:132])
    # RSA-OAEP: unmask the seed, then the data block; the AES key is its last 16 bytes.
    seed = _xor(decrypted[1:21], mgf1(decrypted[21:128], 20))
    aes_key = _xor(decrypted[21:128], mgf1(seed, 107))[-16:]
    if response[134:136] != b"\x03\x40":
        raise MtpzError("Unexpected handshake reply from the device")
    message = AES.new(aes_key, AES.MODE_CBC, iv=bytes(16)).decrypt(response[136:136 + 832])

    offset = 1
    (certs_length,) = struct.unpack_from(">I", message, offset)
    offset += 4 + certs_length

    def field() -> bytes:
        nonlocal offset
        (length,) = struct.unpack_from(">H", message, offset)
        value = message[offset + 2:offset + 2 + length]
        offset += 2 + length
        return value

    if field()[:16] != random:
        raise MtpzError("The device failed the handshake check")
    field()  # device random
    offset += 1
    field()  # signature
    offset += 1
    return field()


def cmac(key: bytes, message: bytes) -> bytes:
    return CMAC.new(key, message, ciphermod=AES).digest()


def handshake(device: mtp.MtpDevice, keys: Keys) -> None:
    """Authenticate an open session so the device accepts writes."""
    device.set_device_prop(SESSION_INITIATOR_INFO, mtp.STR, INITIATOR)
    device.call(END_TRUSTED_APP_SESSION)
    random = os.urandom(16)
    device.call(SEND_APP_REQUEST, data=certificate_message(keys, random))
    _, response = device.call(GET_APP_RESPONSE)
    digest = session_hash(keys, response, random)
    device.call(SEND_APP_REQUEST, data=b"\x02\x03\x00\x10" + cmac(digest[:16], bytes(15) + b"\x01"))
    mac = cmac(digest[:16], digest[16:20])
    device.call(ENABLE_TRUSTED_FILE_OPERATIONS, *struct.unpack(">4I", mac))
