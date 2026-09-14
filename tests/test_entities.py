"""Entity behaviour: naming, optimistic state and error reporting."""

from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from .const import DEVICE_INFO_ON, TOGGLE_URL


async def test_entities_created_for_each_relay(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """Two relays plus three diagnostics, and no fan.

    Relay 2 is labelled "Fan" by the user, but `features` reports SWITCH, so the
    hardware capability must win over the label.
    """
    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, loaded_entry.entry_id)
    unique_ids = {e.unique_id for e in entities}

    assert unique_ids == {
        "669b9361c3ff9afe7633de52_1",
        "669b9361c3ff9afe7633de52_2",
        "669b9361c3ff9afe7633de52_rssi",
        "669b9361c3ff9afe7633de52_ssid",
        "669b9361c3ff9afe7633de52_ip",
    }
    assert not [e for e in entities if e.domain == "fan"]


async def test_signal_sensor_is_disabled_by_default(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """RSSI changes every poll, so it must not fill the recorder unasked."""
    registry = er.async_get(hass)
    entities = {
        e.unique_id: e
        for e in er.async_entries_for_config_entry(registry, loaded_entry.entry_id)
    }
    assert entities["669b9361c3ff9afe7633de52_rssi"].disabled_by is not None
    assert entities["669b9361c3ff9afe7633de52_ssid"].disabled_by is None


async def test_entity_names_use_the_full_device_name(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """Bronze `has-entity-name` composes "<device> <entity>".

    The device name used to be derived with `name.split(" ")[0]`, which would
    have truncated a multi-word device name to its first word.
    """
    state = hass.states.get("switch.hall_led")
    assert state.attributes["friendly_name"] == "Hall LED"


async def test_optimistic_state_shows_while_command_is_in_flight(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """The dashboard must not wait for the queue plus a poll.

    The command is held open so the state can be observed mid-flight, which is
    the window the optimistic value exists for.
    """
    import asyncio

    hub = loaded_entry.runtime_data.hubs[0]
    release = asyncio.Event()

    async def _slow_command(*args):
        await release.wait()
        return True

    assert hass.states.get("switch.hall_led").state == STATE_OFF

    with patch.object(hub, "queue_toggle_command", _slow_command):
        task = hass.async_create_task(
            hass.services.async_call(
                "switch", "turn_on", {ATTR_ENTITY_ID: "switch.hall_led"}, blocking=True
            )
        )
        await asyncio.sleep(0)  # let the optimistic write land
        assert hass.states.get("switch.hall_led").state == STATE_ON

        release.set()
        await task
        await hass.async_block_till_done()


async def test_state_follows_the_device_once_it_reports(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, device_online: AiohttpClientMocker
) -> None:
    """A relay that really switched stays on after the poll."""
    device_online.clear_requests()
    device_online.get("http://10.0.28.17/info", json=DEVICE_INFO_ON)
    device_online.post(TOGGLE_URL, json={})

    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: "switch.hall_led"}, blocking=True
    )
    await hass.async_block_till_done()

    assert hass.states.get("switch.hall_led").state == STATE_ON


async def test_optimistic_guess_reverts_if_the_relay_did_not_move(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """Polled truth always wins, so a command that did nothing shows as off."""
    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: "switch.hall_led"}, blocking=True
    )
    await hass.async_block_till_done()

    # the device is still reporting state "00"
    assert hass.states.get("switch.hall_led").state == STATE_OFF


async def test_failed_command_surfaces_to_the_user(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, device_online: AiohttpClientMocker
) -> None:
    """A rejected command must not fail silently."""
    device_online.clear_requests()
    device_online.get("http://10.0.28.17/info", json={"state": "00", "rssi": -60,
        "ip": "10.0.28.17", "version": 82, "status": 1, "chip_id": "11509299",
        "ssid": "x", "firmware": 82, "model": "WIFI_2SWITCH_V1"})
    device_online.post(TOGGLE_URL, status=400)

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "switch", "turn_on", {ATTR_ENTITY_ID: "switch.hall_led"}, blocking=True
        )

    assert hass.states.get("switch.hall_led").state == STATE_OFF


async def test_a_second_switch_keeps_its_state_while_queued(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """Operating one switch must not snap a second one back.

    Commands to one device are queued and spaced, so the second switch waits
    behind the first. The first one's refresh used to clear the second's
    optimistic value before its command had even been sent, so it flicked back
    to its old state and only corrected a second later when its own command
    landed.
    """
    import asyncio

    hub = loaded_entry.runtime_data.hubs[0]
    release = asyncio.Event()

    async def _slow_command(*args, **kwargs):
        await release.wait()
        return True

    assert hass.states.get("switch.hall_fan").state == STATE_OFF

    with patch.object(hub, "queue_toggle_command", _slow_command):
        task = hass.async_create_task(
            hass.services.async_call(
                "switch", "turn_on", {ATTR_ENTITY_ID: "switch.hall_fan"}, blocking=True
            )
        )
        await asyncio.sleep(0)
        assert hass.states.get("switch.hall_fan").state == STATE_ON

        # The first switch's command finishes and the coordinator notifies every
        # entity. That notification is what used to clear this entity's guess.
        # No async_block_till_done here: the command above is deliberately held
        # open, and waiting for every task would wait for it too.
        loaded_entry.runtime_data.async_update_listeners()
        await asyncio.sleep(0)

        # the queued switch must still show what the user asked for
        assert hass.states.get("switch.hall_fan").state == STATE_ON

        release.set()
        await task
        await hass.async_block_till_done()
