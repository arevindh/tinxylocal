"""The Tinxy Local integration."""

from __future__ import annotations

import os
import stat
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_DEVICE, CONF_MQTT_PASS, DOMAIN
from .coordinator import TinxyUpdateCoordinator
from .hub import TinxyLocalHub

_LOGGER = logging.getLogger(__name__)

# List the platforms that this integration will support.
PLATFORMS: list[Platform] = [Platform.SWITCH, Platform.NUMBER, Platform.FAN, Platform.LOCK]


def set_executable_permissions(directory: str):
    """Ensure all files in the directory are executable."""
    for root, _, files in os.walk(directory):
        for file in files:
            file_path = os.path.join(root, file)
            if not os.access(file_path, os.X_OK):
                current_perms = os.stat(file_path).st_mode
                os.chmod(file_path, current_perms | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tinxy from a config entry."""

    hass.data.setdefault(DOMAIN, {})

    # Set executable permissions for files in the build directory
    integration_path = hass.config.path("custom_components/tinxylocal/build")
    if os.path.exists(integration_path):
        _LOGGER.info("Setting executable permissions for files in %s", integration_path)
        set_executable_permissions(integration_path)
    else:
        _LOGGER.warning("Build directory does not exist: %s", integration_path)

    web_session = async_get_clientsession(hass)

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
    hubs = [TinxyLocalHub(hass, node["ip_address"]) for node in nodes]

    # Initialize the coordinator with the list of nodes and web session
    coordinator = TinxyUpdateCoordinator(hass, nodes, web_session)

    # Store the coordinator and hubs in Home Assistant's data store
    hass.data[DOMAIN][entry.entry_id] = {"coordinator": coordinator, "hubs": hubs}

    # Forward the entry setup to the platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
