"""Coordinator behaviour at the Home Assistant level.

Decoding of the device payload itself is covered by the tinxy package.
"""

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from homeassistant.core import HomeAssistant



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
    status = next(iter(loaded_entry.runtime_data.data.values()))
    assert status.firmware == "82"
    assert isinstance(status.firmware, str)
