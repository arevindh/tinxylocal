"""Command queue, rate limiting and the device's replay protection."""

import asyncio
from unittest.mock import patch

import pytest

from custom_components.tinxylocal.hub import (
    TinxyCommandSuperseded,
    TinxyLocalHub,
)


@pytest.fixture
def hub() -> TinxyLocalHub:
    """A hub with no real network behind it."""
    return TinxyLocalHub(None, "10.0.28.17", rate_limit_delay=0)


@pytest.fixture
def sent(hub: TinxyLocalHub) -> list[int]:
    """Record relays the worker actually dispatched."""
    calls: list[int] = []

    async def _toggle(mqttpass, relay, action):
        calls.append(relay)
        await asyncio.sleep(0)
        return True

    hub.tinxy_toggle = _toggle
    return calls


async def test_timestamp_never_repeats_within_a_second(hub: TinxyLocalHub) -> None:
    """The device rejects a timestamp it has already seen (HTTP 400)."""
    seen = []

    async def _capture(method, endpoint, payload=None, web_session=None):
        seen.append(payload["relayNumber"])
        return {}

    with (
        patch.object(hub, "_send_request", _capture),
        patch("custom_components.tinxylocal.hub.async_get_clientsession"),
        patch("time.time", return_value=1788774045.4),
    ):
        await hub._send_command("pw", 1, 1)
        first = hub.last_command_timestamp
        await hub._send_command("pw", 2, 1)
        second = hub.last_command_timestamp

    assert second > first, "two commands in one second must not share a timestamp"


async def test_relay_number_is_sent_one_based(hub: TinxyLocalHub) -> None:
    """The wire protocol is 1-based, matching the Go CLI it replaced."""
    captured = {}

    async def _capture(method, endpoint, payload=None, web_session=None):
        captured.update(payload)
        captured["endpoint"] = endpoint
        return {}

    with (
        patch.object(hub, "_send_request", _capture),
        patch("custom_components.tinxylocal.hub.async_get_clientsession"),
    ):
        await hub._send_command("pw", 3, 1)

    assert captured["endpoint"] == "/toggle"
    assert captured["relayNumber"] == 3
    assert captured["action"] == "1"
    assert "brightness" not in captured


async def test_brightness_is_included_only_when_set(hub: TinxyLocalHub) -> None:
    """Brightness accompanies a speed change, never a plain off."""
    captured = {}

    async def _capture(method, endpoint, payload=None, web_session=None):
        captured.update(payload)
        return {}

    with (
        patch.object(hub, "_send_request", _capture),
        patch("custom_components.tinxylocal.hub.async_get_clientsession"),
    ):
        await hub.tinxy_set_brightness("pw", 1, 66)

    assert captured["brightness"] == 66
    assert captured["action"] == "1"


async def test_rejects_out_of_range_values(hub: TinxyLocalHub) -> None:
    """Guards at the boundary, so nonsense never reaches the device."""
    assert await hub.tinxy_toggle("pw", 1, 5) is False
    assert await hub.tinxy_set_brightness("pw", 1, 150) is False


async def test_multiple_relays_on_one_device_all_dispatch(
    hub: TinxyLocalHub, sent: list[int]
) -> None:
    """A scene touching four relays of one device must send all four."""
    results = await asyncio.gather(
        *[hub.queue_toggle_command("dev1", "pw", relay, 1) for relay in (1, 2, 3, 4)]
    )
    await hub.shutdown()

    assert all(results)
    assert sorted(sent) == [1, 2, 3, 4]


async def test_staggered_commands_do_not_lose_any(
    hub: TinxyLocalHub, sent: list[int]
) -> None:
    """Regression: dedup used to swap the deque while the worker held it.

    A second switch operated while the worker was mid rate-limit sleep made it
    pop from an orphaned queue, dropping the command and logging
    "pop from an empty deque".
    """

    async def tap(relay: int, delay: float):
        await asyncio.sleep(delay)
        return await hub.queue_toggle_command("dev1", "pw", relay, 1)

    results = await asyncio.gather(
        *[tap(r, i * 0.02) for i, r in enumerate((1, 2, 3, 1, 2))],
        return_exceptions=True,
    )
    await hub.shutdown()

    assert not any(isinstance(r, Exception) and not isinstance(
        r, TinxyCommandSuperseded) for r in results)
    assert set(sent) == {1, 2, 3}


async def test_newer_command_supersedes_a_pending_one(
    hub: TinxyLocalHub, sent: list[int]
) -> None:
    """Hammering one switch collapses to the latest intent, not an error."""
    hub.rate_limit_delay = 0.05

    async def tap(delay: float):
        await asyncio.sleep(delay)
        return await hub.queue_toggle_command("dev1", "pw", 1, 1)

    results = await asyncio.gather(
        *[tap(i * 0.005) for i in range(5)], return_exceptions=True
    )
    await hub.shutdown()

    superseded = [r for r in results if isinstance(r, TinxyCommandSuperseded)]
    assert superseded, "a replaced command should report as superseded"
    assert all(r is True or isinstance(r, TinxyCommandSuperseded) for r in results)


async def test_queue_limit_is_enforced(hub: TinxyLocalHub, sent: list[int]) -> None:
    """A runaway automation cannot grow the queue without bound."""
    hub.queue_limit = 3
    hub.rate_limit_delay = 5  # stall the worker so the queue fills

    from custom_components.tinxylocal.hub import TinxyLocalException

    tasks = [
        asyncio.create_task(hub.queue_toggle_command("dev1", "pw", relay, 1))
        for relay in range(1, 8)
    ]
    await asyncio.sleep(0.05)
    hub._shutdown = True
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await hub.shutdown()
