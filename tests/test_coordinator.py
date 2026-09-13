"""Coordinator behaviour: availability and metadata typing."""

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from homeassistant.core import HomeAssistant

from custom_components.tinxylocal.hub import TinxyLocalHub

from .const import DEVICE_INFO, FAN_INFO


async def test_entities_go_unavailable_when_device_stops_answering(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, device_online: AiohttpClientMocker
) -> None:
    """A silent device must not keep serving its last known state."""
    assert hass.states.get("switch.hall_led").state == "off"

    device_online.clear_requests()
    device_online.get("http://10.0.28.17/info", status=500)

    coordinator = loaded_entry.runtime_data
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert coordinator.last_update_success is False
    assert hass.states.get("switch.hall_led").state == "unavailable"


async def test_firmware_is_coerced_to_string(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """The device reports firmware as an int; HA 2026.12 requires a string."""
    metadata = loaded_entry.runtime_data.device_metadata
    firmware = next(iter(metadata.values()))["firmware"]
    assert firmware == "82"
    assert isinstance(firmware, str)


def test_decode_handles_a_switch_payload() -> None:
    """Relay states come from the state bitmask, one character per relay."""
    node = {"devices": [{"name": "LED", "type": "LED Bulb"},
                        {"name": "Fan", "type": "Fan"}]}
    decoded = TinxyLocalHub._decode_device_data({**DEVICE_INFO, "state": "01"}, node)

    assert decoded["rssi"] == -60
    assert decoded["door"] is None  # absent on switches, must not KeyError
    assert [d["status"] for d in decoded["devices"]] == ["off", "on"]


def test_decode_splits_brightness_into_three_digit_chunks() -> None:
    """`bright` is 3 digits per relay, and only lights and fans carry it."""
    node = {"devices": [{"name": "fan 1", "type": "Fan"},
                        {"name": "switch 2", "type": "Socket"},
                        {"name": "switch 3", "type": "Socket"},
                        {"name": "switch 4", "type": "Socket"}]}
    decoded = TinxyLocalHub._decode_device_data(FAN_INFO, node)

    assert decoded["devices"][0]["status"] == "on"
    assert decoded["devices"][0]["brightness"] == 100
    assert "brightness" not in decoded["devices"][1]
