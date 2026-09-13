"""The Tinxy Local integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import slugify

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
from tinxy import TinxyLocalClient

from .coordinator import TinxyConfigEntry, TinxyUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# List the platforms that this integration will support.
PLATFORMS: list[Platform] = [
    Platform.SWITCH,
    Platform.FAN,
    Platform.LOCK,
    Platform.SENSOR,
]


def _relays(device: dict) -> list[dict]:
    """Return the relays of a stored cloud device, as name and type.

    Mirrors `CloudDevice.relays()` in the tinxy package. Some devices report
    neither relay names nor types, only a count, so the count is the fallback:
    without it a one-gang unit yields no relays and therefore no entities.

    Kept here rather than taken from the package because the entry stores the
    raw API payload and the package's parser is not public. Replace this with
    `CloudDevice.from_api(...)` once the package exposes one.
    """
    type_id = device.get("typeId") or {}
    names = device.get("devices") or []
    kinds = device.get("deviceTypes") or []
    features = type_id.get("features") or []
    is_lock = type_id.get("gtype") == "action.devices.types.LOCK"
    count = max(len(names), len(kinds), int(type_id.get("numberOfRelays") or 0))

    def kind_at(i: int) -> str:
        if i < len(kinds):
            return kinds[i]
        if is_lock:
            return "Lock"
        # Capabilities can be combined, as in "SWITCH|FAN", so test as substring.
        return "Fan" if i < len(features) and "FAN" in features[i] else "Socket"

    return [
        {
            "name": names[i]
            if i < len(names)
            else (device["name"] if count == 1 else f"Relay {i + 1}"),
            "type": kind_at(i),
        }
        for i in range(count)
    ]


def _async_repair_doubled_entity_ids(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Strip a duplicated device name from generated entity ids.

    Upgrading from 2.x produced ids like `sensor.hall_hall_ip_address`: the
    device name appears twice. Fresh installs are unaffected, and the displayed
    name, state and history were always correct, so this is cosmetic. The cause
    sits in how Home Assistant derived the id during that particular upgrade and
    has not been reproduced outside it, so this repairs the result rather than
    the cause.

    Only entities this integration created are touched, only where the doubled
    prefix is actually present, and only when the corrected id is free.
    """
    registry = er.async_get(hass)
    for item in er.async_entries_for_config_entry(registry, entry.entry_id):
        device = registry.async_get(item.entity_id)
        if not device or not item.has_entity_name:
            continue

        domain, _, object_id = item.entity_id.partition(".")
        entry_title = slugify(entry.title)
        doubled = f"{entry_title}_{entry_title}_"
        if not object_id.startswith(doubled):
            continue

        fixed = f"{domain}.{object_id.replace(doubled, f'{entry_title}_', 1)}"
        if registry.async_get(fixed):
            continue

        _LOGGER.info("Renaming %s to %s", item.entity_id, fixed)
        registry.async_update_entity(item.entity_id, new_entity_id=fixed)


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
    _async_repair_doubled_entity_ids(hass, entry)

    web_session = async_get_clientsession(hass)

    # Get request timeout from options or use default
    request_timeout = entry.options.get(CONF_REQUEST_TIMEOUT, DEFAULT_REQUEST_TIMEOUT)
    
    # Get polling interval from options or use default
    polling_interval = entry.options.get(CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL)

    # Spacing between commands to one device
    rate_limit_delay = entry.options.get(CONF_RATE_LIMIT_DELAY, DEFAULT_RATE_LIMIT_DELAY)

    device_data = entry.data[CONF_DEVICE]
    type_id = device_data.get("typeId") or {}

    nodes = [
        {
            "ip_address": entry.data[CONF_HOST],
            "mqtt_password": entry.data[CONF_MQTT_PASS],
            "device_id": device_data["_id"],
            "name": device_data["name"],
            "model": type_id.get("name"),
            "unique_id": device_data["_id"],
            "devices": _relays(device_data),
        }
    ]

    clients = [
        TinxyLocalClient(
            node["ip_address"],
            web_session,
            request_timeout=request_timeout,
            command_spacing=rate_limit_delay,
        )
        for node in nodes
    ]

    coordinator = TinxyUpdateCoordinator(
        hass, entry, nodes, clients, polling_interval
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
        for client in entry.runtime_data.clients:
            await client.aclose()
    return unload_ok
