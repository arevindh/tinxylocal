"""Self-check for the XXTEA token the device firmware authenticates against.

Run directly: python3 custom_components/tinxylocal/test_crypto.py
"""

from crypto import encrypt_tinxy_payload


def test_parity_with_retired_go_cli() -> None:
    """Known-good vector captured from the Go CLI this module replaced."""
    assert (
        encrypt_tinxy_payload("my_secret_device_pass", timestamp=1788774045)
        == "3682322e3fd66d7760c87c8b"
    )


def test_timestamp_changes_token() -> None:
    """A different timestamp must produce a different token, or the device replay-rejects."""
    a = encrypt_tinxy_payload("pass", timestamp=1788774045)
    b = encrypt_tinxy_payload("pass", timestamp=1788774046)
    assert a != b


if __name__ == "__main__":
    test_parity_with_retired_go_cli()
    test_timestamp_changes_token()
    print("ok")
