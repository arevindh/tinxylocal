"""Lock platform: a pulse relay with no real lock state to read back."""

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant

from custom_components.tinxylocal.const import DOMAIN

from .const import CLOUD_LOCK, DEVICE_INFO, ENTRY_DATA, HOST

LOCK_DEVICE = {**CLOUD_LOCK, "devices": ["Lock"]}


async def _setup_lock(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, info):
    aioclient_mock.get(f"http://{HOST}/info", json=info)
    aioclient_mock.post(f"http://{HOST}/toggle", json={})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Front Door",
        unique_id="5610150",
        data={**ENTRY_DATA, "device": LOCK_DEVICE},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_lock_entity_replaces_the_switches(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A LOCK gtype produces one lock and no switch or fan entities."""
    await _setup_lock(hass, aioclient_mock, {**DEVICE_INFO, "state": "0"})

    assert hass.states.get("lock.front_door") is not None
    assert not [e for e in hass.states.async_entity_ids() if e.startswith("switch.")]


async def test_open_door_reads_as_unlocked(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The `door` field wins over relay state when the firmware reports it."""
    await _setup_lock(
        hass, aioclient_mock, {**DEVICE_INFO, "state": "0", "door": "OPEN"}
    )
    assert hass.states.get("lock.front_door").state == "unlocked"


async def test_closed_door_reads_as_locked(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A closed door with an idle relay is locked."""
    await _setup_lock(
        hass, aioclient_mock, {**DEVICE_INFO, "state": "0", "door": "CLOSED"}
    )
    state = hass.states.get("lock.front_door")
    assert state.state == "locked"
    assert state.attributes["door_status"] == "CLOSED"


async def test_unlock_sends_a_pulse(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Unlocking is a single action=1 pulse; the device re-locks on its timer."""
    entry = await _setup_lock(hass, aioclient_mock, {**DEVICE_INFO, "state": "0"})
    hub = entry.runtime_data.hubs[0]
    sent = []

    async def _capture(device_id, mqttpass, relay, action):
        sent.append((relay, action))
        return True

    hub.queue_toggle_command = _capture

    await hass.services.async_call(
        "lock", "unlock", {ATTR_ENTITY_ID: "lock.front_door"}, blocking=True
    )
    await hass.async_block_till_done()

    assert sent == [(1, 1)]


async def test_lock_command_is_a_no_op(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """There is no lock command in the protocol, so nothing is sent."""
    entry = await _setup_lock(hass, aioclient_mock, {**DEVICE_INFO, "state": "0"})
    hub = entry.runtime_data.hubs[0]
    sent = []

    async def _capture(*args):
        sent.append(args)
        return True

    hub.queue_toggle_command = _capture

    await hass.services.async_call(
        "lock", "lock", {ATTR_ENTITY_ID: "lock.front_door"}, blocking=True
    )
    await hass.async_block_till_done()

    assert sent == []
