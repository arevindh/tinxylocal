"""Pure-Python XXTEA encryption for Tinxy local device communication.

Adapted from the ha-tinxylocal fork by @selvakk2k
(https://github.com/selvakk2k/ha-tinxylocal), which established that the Tinxy
local auth token can be produced in pure Python and removed the need for the
bundled Go binaries this integration used to ship.

Output is byte-identical to the retired `tinxy-cli`: verified across 319 cases
covering key lengths either side of the 16-byte boundary and timestamps either
side of the 4-byte block boundary. See test_crypto.py for the pinned vector.
"""

from __future__ import annotations

import struct
import time


def str_to_longs(s: bytes) -> list[int]:
    """Convert bytes to a list of 32-bit unsigned integers (little-endian)."""
    n = (len(s) + 3) // 4
    v = [0] * n
    for i, b in enumerate(s):
        v[i // 4] |= b << ((i % 4) * 8)
    return v


def longs_to_bytes(v: list[int]) -> bytes:
    """Convert a list of 32-bit unsigned integers back to little-endian bytes."""
    res = bytearray()
    for val in v:
        res.extend(struct.pack("<I", val & 0xFFFFFFFF))
    return bytes(res)


def derive_key(key: bytes) -> list[int]:
    """Derive a 128-bit key (4 uint32s) padded or truncated to 16 bytes."""
    if len(key) < 16:
        key = key + b"\x00" * (16 - len(key))
    else:
        key = key[:16]
    return str_to_longs(key)


def xxtea_encrypt(v: list[int], k: list[int]) -> list[int]:
    """Execute standard XXTEA encryption rounds."""
    n = len(v)
    if n < 2:
        v.append(0)
        n = len(v)

    delta = 0x9E3779B9
    rounds = 6 + 52 // n
    sum_val = 0
    z = v[n - 1]

    for _ in range(rounds):
        sum_val = (sum_val + delta) & 0xFFFFFFFF
        e = (sum_val >> 2) & 3
        for p in range(n):
            y = v[(p + 1) % n]
            term1 = (((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4))) & 0xFFFFFFFF
            term2 = ((sum_val ^ y) + (k[(p & 3) ^ e] ^ z)) & 0xFFFFFFFF
            mx = (term1 ^ term2) & 0xFFFFFFFF
            v[p] = (v[p] + mx) & 0xFFFFFFFF
            z = v[p]

    return v


def encrypt_tinxy_payload(password: str, timestamp: int | None = None) -> str:
    """Encrypt the current unix timestamp with the device password using XXTEA.

    Returns the encrypted token formatted as a lowercase hex string.
    """
    if timestamp is None:
        timestamp = int(time.time())

    msg = str(timestamp).encode("utf-8")
    v = str_to_longs(msg)
    k = derive_key(password.encode("utf-8"))
    enc_v = xxtea_encrypt(v, k)
    return longs_to_bytes(enc_v).hex().lower()
