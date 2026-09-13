"""Fixtures for the Tinxy Local tests."""

from collections.abc import Generator
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tinxylocal.const import DOMAIN

from .const import CHIP_ID, CLOUD_DEVICES, DEVICE_INFO, ENTRY_DATA, INFO_URL, TOGGLE_URL


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load the integration from custom_components during tests."""
    return


@pytest.fixture(autouse=True)
def no_command_spacing() -> Generator[None]:
    """Drop the 1s command floor and the settle delay so tests are not slow.

    The spacing is a device protocol constraint, not integration logic, and it
    is covered directly in test_hub.py.
    """
    with (
        patch("custom_components.tinxylocal.hub.DEFAULT_RATE_LIMIT_DELAY", 0),
        patch("custom_components.tinxylocal.entity.SETTLE_DELAY", 0),
    ):
        yield


@pytest.fixture
def device_online(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """A reachable device and a working cloud account."""
    aioclient_mock.get(INFO_URL, json=DEVICE_INFO)
    aioclient_mock.post(TOGGLE_URL, json={})
    aioclient_mock.get("https://backend.tinxy.in/v2/devices/", json=CLOUD_DEVICES)
    return aioclient_mock


@pytest.fixture
def mock_entry() -> MockConfigEntry:
    """A config entry as the current version creates it."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Hall",
        data=ENTRY_DATA,
        unique_id=CHIP_ID,
    )


@pytest.fixture
async def loaded_entry(
    hass: HomeAssistant, device_online, mock_entry: MockConfigEntry
) -> MockConfigEntry:
    """A fully set up entry."""
    mock_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    return mock_entry
