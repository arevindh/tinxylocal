"""Tinxy Node Update Coordinator."""

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .hub import TinxyConnectionException, TinxyLocalException, TinxyLocalHub

_LOGGER = logging.getLogger(__name__)
REQUEST_REFRESH_DELAY = 0.50

# Bronze `runtime-data`: the coordinator lives on the entry, not in hass.data.
# It owns the hubs, so it is the only thing the platforms need.
type TinxyConfigEntry = ConfigEntry[TinxyUpdateCoordinator]


class TinxyUpdateCoordinator(DataUpdateCoordinator):
    """Coordinator to fetch data directly from Tinxy nodes."""

    device_metadata: dict[str, dict[str, Any]]
    nodes: list[dict[str, Any]]

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        nodes: list[dict[str, Any]],
        web_session,
        hubs: list[TinxyLocalHub],
        default_polling_interval: int = 5,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="Tinxy Nodes",
            config_entry=config_entry,
            update_interval=timedelta(seconds=default_polling_interval),
        )
        self.hass = hass
        self.nodes = nodes  # Type-annotated as a list of dictionaries
        self.web_session = web_session
        # Shared with the platforms, so polling honours the configured timeout
        # and commands queue against the same per-device worker.
        self.hubs = hubs
        self.device_metadata = {}  # Type-annotated as a dictionary
        self._devices_registered = False

    async def _async_update_data(self):
        """Fetch data from each configured Tinxy node."""
        status_list = {}
        errors = []
        for hub, node in zip(self.hubs, self.nodes, strict=False):
            try:
                device_data = await hub.fetch_device_data(node, self.web_session)
                if device_data:
                    status_list[node["device_id"]] = device_data
                    # Populate device metadata for other information (firmware, model, etc.)
                    self.device_metadata[node["device_id"]] = {
                        # str(): the device reports firmware as an int, and HA
                        # rejects a non-string sw_version from 2026.12. Coerced
                        # here so all five device_info consumers get a string.
                        "firmware": str(device_data.get("firmware", "Unknown")),
                        "model": device_data.get("model", "Tinxy Smart Device"),
                        "rssi": device_data.get("rssi"),
                        "ssid": device_data.get("ssid"),
                        "ip": device_data.get("ip"),
                        "version": device_data.get("version"),
                        "door": device_data.get("door"),
                    }
            except (TinxyConnectionException, TinxyLocalException) as err:
                errors.append(f"{node['name']}: {err}")

        # A node that stops answering must mark its entities unavailable rather than
        # leave them showing the last state it happened to report. DataUpdateCoordinator
        # logs this once and keeps the previous self.data, so entities can fall back to
        # `last_update_success` instead of stale values.
        if not status_list:
            raise UpdateFailed("; ".join(errors) or "No Tinxy node returned data")

        _LOGGER.debug("Coordinator data updated: %s", status_list)

        if not self._devices_registered:
            await self._register_devices()
            self._devices_registered = True
        return status_list

    async def _register_devices(self):
        """Register devices in the Home Assistant device registry after data is loaded."""
        device_registry = dr.async_get(self.hass)
        for node in self.nodes:
            metadata = self.device_metadata.get(node["device_id"], {})
            firmware_version = metadata.get("firmware", "Unknown")
            model = metadata.get("model", "Tinxy Smart Device")

            # Only use identifiers without connections
            device_registry.async_get_or_create(
                config_entry_id=self.config_entry.entry_id,
                identifiers={(DOMAIN, node["device_id"])},
                name=node["name"],
                manufacturer="Tinxy",
                model=model,
                sw_version=firmware_version,
            )
