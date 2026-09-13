"""The Tinxy Local integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_DEVICE,
    CONF_DEVICE_ID,
    CONF_MQTT_PASS,
    CONF_POLLING_INTERVAL,
    CONF_RATE_LIMIT_DELAY,
    CONF_REQUEST_TIMEOUT,
    DEFAULT_POLLING_INTERVAL,
    DEFAULT_RATE_LIMIT_DELAY,
    DEFAULT_REQUEST_TIMEOUT,
)
from .coordinator import TinxyConfigEntry, TinxyUpdateCoordinator
from .hub import TinxyLocalHub

_LOGGER = logging.getLogger(__name__)

# List the platforms that this integration will support.
PLATFORMS: list[Platform] = [
    Platform.SWITCH,
    Platform.FAN,
    Platform.LOCK,
    Platform.SENSOR,
]


def _async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Bring entries created before 3.0.0 up to date, in place.

    * Entries added before zeroconf existed have no `unique_id`, so discovery
      cannot tell they are already configured and would offer the same device
      again as new, producing a duplicate entry and a second set of entities.
      The chip id has always been stored as `device_id`, so adopt it.
    """
    # Only entries predating 3.0.0 lack a unique_id; the config flow always sets
    # one now, so this is the reliable marker for a legacy entry.
    if entry.unique_id is not None:
        return

    updates: dict = {}

    if entry.data.get(CONF_DEVICE_ID):
        updates["unique_id"] = entry.data[CONF_DEVICE_ID]

    if updates:
        _LOGGER.info("Migrating Tinxy entry %s: %s", entry.title, sorted(updates))
        hass.config_entries.async_update_entry(entry, **updates)


async def async_setup_entry(hass: HomeAssistant, entry: TinxyConfigEntry) -> bool:
    """Set up Tinxy from a config entry."""

    _async_migrate_entry(hass, entry)

    web_session = async_get_clientsession(hass)

    # Get request timeout from options or use default
    request_timeout = entry.options.get(CONF_REQUEST_TIMEOUT, DEFAULT_REQUEST_TIMEOUT)
    
    # Get polling interval from options or use default
    polling_interval = entry.options.get(CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL)

    # Spacing between commands to one device
    rate_limit_delay = entry.options.get(CONF_RATE_LIMIT_DELAY, DEFAULT_RATE_LIMIT_DELAY)

    # Extract device configurations
    device_data = entry.data[CONF_DEVICE]

    nodes = [
        {
            "ip_address": entry.data[CONF_HOST],
            "mqtt_password": entry.data[CONF_MQTT_PASS],
            "device_id": device_data["_id"],
            "name": device_data["name"],
            "model": device_data["typeId"]["name"],
            "unique_id": device_data["_id"],
            "devices": [
                {"name": dev_name, "type": dev_type}
                for dev_name, dev_type in zip(
                    device_data["devices"], device_data["deviceTypes"], strict=False
                )
            ] if device_data["devices"] else [
                # For locks and other devices without individual relays, create a single device entry
                {"name": device_data["name"], "type": "Lock"}
            ] if device_data.get("typeId", {}).get("gtype") == "action.devices.types.LOCK" else [],
        }
    ]

    # Initialize TinxyLocalHub instances for each node
    hubs = [
        TinxyLocalHub(hass, node["ip_address"], request_timeout, rate_limit_delay)
        for node in nodes
    ]

    # Initialize the coordinator with the list of nodes and web session
    coordinator = TinxyUpdateCoordinator(
        hass, entry, nodes, web_session, hubs, polling_interval
    )

    # Bronze `test-before-setup`: fail setup with ConfigEntryNotReady if the
    # device cannot be reached, so Home Assistant retries instead of bringing up
    # a config entry whose entities never had any data.
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: TinxyConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        # Stop the per-device command workers.
        for hub in entry.runtime_data.hubs:
            await hub.shutdown()
    return unload_ok
