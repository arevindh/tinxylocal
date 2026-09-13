"""XXTEA parity with the Go CLI this integration replaced.

The vector below was produced by the original `tinxy-cli` binary. If a change
to the rounds breaks it, the device will reject every command with HTTP 400.
"""

import pytest

from custom_components.tinxylocal.crypto import (
    derive_key,
    encrypt_tinxy_payload,
    longs_to_bytes,
    str_to_longs,
)


def test_matches_the_retired_go_cli() -> None:
    """Known-good output from the compiled CLI."""
    assert (
        encrypt_tinxy_payload("my_secret_device_pass", timestamp=1788774045)
        == "3682322e3fd66d7760c87c8b"
    )


@pytest.mark.parametrize("length", [1, 4, 8, 15, 16, 17, 32])
def test_key_is_always_16_bytes(length: int) -> None:
    """Short keys pad, long keys truncate; either way four uint32 words."""
    assert len(derive_key(b"p" * length)) == 4


@pytest.mark.parametrize("timestamp", [1, 1234, 12345, 1788774045, 99999999999])
def test_round_trips_across_block_boundaries(timestamp: int) -> None:
    """Timestamps either side of the 4-byte block boundary survive."""
    token = encrypt_tinxy_payload("device-key", timestamp=timestamp)
    assert len(token) % 2 == 0
    # decrypting proves the payload really is the timestamp
    assert _decrypt(token, "device-key") == timestamp


def test_every_second_produces_a_different_token() -> None:
    """The device rejects a repeated timestamp, so tokens must differ."""
    a = encrypt_tinxy_payload("key", timestamp=1788774045)
    b = encrypt_tinxy_payload("key", timestamp=1788774046)
    assert a != b


def _decrypt(token_hex: str, password: str) -> int:
    """Reverse of encrypt_tinxy_payload, for the round-trip test only."""
    v = str_to_longs(bytes.fromhex(token_hex))
    k = derive_key(password.encode())
    n = len(v)
    delta = 0x9E3779B9
    rounds = 6 + 52 // n
    total = (rounds * delta) & 0xFFFFFFFF
    y = v[0]
    for _ in range(rounds):
        e = (total >> 2) & 3
        for p in range(n - 1, -1, -1):
            z = v[(p - 1 + n) % n]
            mx = ((((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4))) & 0xFFFFFFFF) ^ (
                ((total ^ y) + (k[(p & 3) ^ e] ^ z)) & 0xFFFFFFFF
            )
            v[p] = (v[p] - mx) & 0xFFFFFFFF
            y = v[p]
        total = (total - delta) & 0xFFFFFFFF
    return int(longs_to_bytes(v).split(b"\x00")[0].decode())
