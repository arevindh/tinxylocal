"""Fan platform: three discrete speeds, and the features-vs-label split."""

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant

from custom_components.tinxylocal.const import DOMAIN

from .const import CLOUD_DEVICE, ENTRY_DATA, FAN_INFO, HOST, MQTT_PASS

FAN_CLOUD_DEVICE = {
    **CLOUD_DEVICE,
    "_id": "fan0000000000000000000f",
    "name": "Bedroom",
    "devices": ["Ceiling", "Light", "Socket", "Spare"],
    "deviceTypes": ["Fan", "Tubelight", "Socket", "Socket"],
    "uuidRef": {"uuid": "3804120"},
    "typeId": {
        **CLOUD_DEVICE["typeId"],
        "name": "WIFI_3SWITCH_1FAN",
        # only relay 1 is really fan hardware
        "features": ["FAN", "SWITCH", "SWITCH", "SWITCH"],
        "numberOfRelays": 4,
    },
}


async def _setup_fan(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker):
    aioclient_mock.get(f"http://{HOST}/info", json=FAN_INFO)
    aioclient_mock.post(f"http://{HOST}/toggle", json={})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Bedroom",
        unique_id="3804120",
        data={**ENTRY_DATA, "device": FAN_CLOUD_DEVICE},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_only_fan_hardware_becomes_a_fan(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """`features` decides, not the user's label in the Tinxy app."""
    await _setup_fan(hass, aioclient_mock)

    assert hass.states.get("fan.bedroom_ceiling") is not None
    # the other three relays are switches even though one is labelled Tubelight
    assert hass.states.get("fan.bedroom_light") is None
    assert hass.states.get("switch.bedroom_light") is not None


async def test_fan_reports_speed_from_the_brightness_field(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """`bright` is "100100000000": relay 1 at 100%."""
    await _setup_fan(hass, aioclient_mock)

    state = hass.states.get("fan.bedroom_ceiling")
    assert state.state == STATE_ON
    assert state.attributes["percentage"] == 100


async def test_fan_speed_snaps_to_the_three_hardware_levels(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The hardware has 33/66/100, so 50% must become 66%, as the CLI did."""
    entry = await _setup_fan(hass, aioclient_mock)
    hub = entry.runtime_data.hubs[0]
    sent = []

    async def _capture(device_id, mqttpass, relay, brightness):
        sent.append(brightness)
        return True

    hub.queue_brightness_command = _capture

    await hass.services.async_call(
        "fan",
        "set_percentage",
        {ATTR_ENTITY_ID: "fan.bedroom_ceiling", "percentage": 50},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert sent == [66]


async def test_fan_off_sends_a_plain_toggle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Turning off must not carry a brightness, matching the device protocol."""
    entry = await _setup_fan(hass, aioclient_mock)
    hub = entry.runtime_data.hubs[0]
    actions = []

    async def _capture(device_id, mqttpass, relay, action):
        actions.append(action)
        return True

    hub.queue_toggle_command = _capture

    await hass.services.async_call(
        "fan", "turn_off", {ATTR_ENTITY_ID: "fan.bedroom_ceiling"}, blocking=True
    )
    await hass.async_block_till_done()

    assert actions == [0]
