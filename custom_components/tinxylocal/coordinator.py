"""Tinxy Node Update Coordinator."""

from datetime import timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .hub import TinxyConnectionException, TinxyLocalException, TinxyLocalHub

_LOGGER = logging.getLogger(__name__)
REQUEST_REFRESH_DELAY = 0.50



class TinxyUpdateCoordinator(DataUpdateCoordinator):
    """Coordinator to fetch data directly from Tinxy nodes."""

    device_metadata: dict[str, dict[str, Any]]
    nodes: list[dict[str, Any]]

    def __init__(
        self,
        hass: HomeAssistant,
        nodes: list[dict[str, Any]],
        hubs: list[TinxyLocalHub],
        web_session,
        default_polling_interval: int = 5,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="Tinxy Nodes",
            update_interval=timedelta(seconds=default_polling_interval),
        )
        self.hass = hass
        self.nodes = nodes
        self.hubs = hubs
        self.web_session = web_session
        self.device_metadata: dict[str, dict[str, Any]] = {}
        self._devices_registered = False

    async def _async_update_data(self):
        """Fetch data from each configured Tinxy node."""
        status_list = {}
        for hub, node in zip(self.hubs, self.nodes, strict=False):
            try:
                device_data = await hub.fetch_device_data(node, self.web_session)
                if device_data:
                    status_list[node["device_id"]] = device_data
                    _LOGGER.debug(
                        "Node %s — IP: %s, RSSI: %s dBm",
                        node["name"],
                        device_data.get("ip"),
                        device_data.get("rssi"),
                    )
                    # Populate device metadata for other information (firmware, model, etc.)
                    self.device_metadata[node["device_id"]] = {
                        "firmware": device_data.get("firmware", "Unknown"),
                        "model": device_data.get("model", "Tinxy Smart Device"),
                        "rssi": device_data.get("rssi"),
                        "ssid": device_data.get("ssid"),
                        "ip": device_data.get("ip"),
                        "version": device_data.get("version"),
                        "door": device_data.get("door"),
                    }
            except TinxyConnectionException as conn_err:
                _LOGGER.error(
                    "Connection error for node %s: %s", node["name"], conn_err
                )
                continue
            except TinxyLocalException as node_err:
                _LOGGER.error(
                    "Error communicating with node %s: %s", node["name"], node_err
                )
                continue

        # Set `self.data` to `status_list` so entities can access it
        self.data = status_list
        _LOGGER.debug("Coordinator data updated: %s", self.data)

        # Register devices only once (not on every poll)
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
