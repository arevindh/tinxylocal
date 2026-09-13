"""Setup, unload and the 3.0.0 upgrade migration."""

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from custom_components.tinxylocal.const import (
    CONF_RATE_LIMIT_DELAY,
    DEFAULT_RATE_LIMIT_DELAY,
    DOMAIN,
)

from .const import CHIP_ID, ENTRY_DATA, INFO_URL


async def test_setup_and_unload(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """The entry loads, exposes its coordinator, and unloads cleanly."""
    assert loaded_entry.state is ConfigEntryState.LOADED
    # Bronze `runtime-data`: no hass.data bucket
    assert DOMAIN not in hass.data
    assert loaded_entry.runtime_data is not None

    assert await hass.config_entries.async_unload(loaded_entry.entry_id)
    await hass.async_block_till_done()
    assert loaded_entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_retries_when_device_unreachable(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Bronze `test-before-setup`: an offline device gives SETUP_RETRY."""
    aioclient_mock.get(INFO_URL, status=500)
    entry = MockConfigEntry(
        domain=DOMAIN, data=ENTRY_DATA, unique_id=CHIP_ID, title="Hall"
    )
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_legacy_entry_adopts_chip_id(
    hass: HomeAssistant, device_online: AiohttpClientMocker
) -> None:
    """Pre-3.0.0 entries have no unique_id, so discovery would duplicate them."""
    entry = MockConfigEntry(
        domain=DOMAIN, data=ENTRY_DATA, unique_id=None, title="Hall"
    )
    entry.add_to_hass(hass)
    assert entry.unique_id is None

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.unique_id == CHIP_ID


async def test_migration_leaves_new_entries_alone(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """An entry created by 3.0.0 keeps the current defaults."""
    assert loaded_entry.unique_id == CHIP_ID
    assert CONF_RATE_LIMIT_DELAY not in loaded_entry.options
    hub = loaded_entry.runtime_data.hubs[0]
    assert hub.rate_limit_delay == DEFAULT_RATE_LIMIT_DELAY


async def test_options_are_applied_to_the_hub(
    hass: HomeAssistant, device_online: AiohttpClientMocker
) -> None:
    """Configured timeout reaches polling, which it did not before 3.0.0."""
    from custom_components.tinxylocal.const import CONF_REQUEST_TIMEOUT

    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        options={CONF_REQUEST_TIMEOUT: 9, CONF_RATE_LIMIT_DELAY: 3},
        unique_id=CHIP_ID,
        title="Hall",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = entry.runtime_data
    # the coordinator must poll through the same hubs the platforms command
    assert coordinator.hubs[0].request_timeout == 9
    assert coordinator.hubs[0].rate_limit_delay == 3
