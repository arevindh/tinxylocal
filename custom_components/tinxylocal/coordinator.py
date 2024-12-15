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
        self, hass: HomeAssistant, nodes: list[dict[str, Any]], web_session
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="Tinxy Nodes",
            update_interval=timedelta(seconds=5),  # Default fallback interval
        )
        self.hass = hass
        self.nodes = nodes  # Type-annotated as a list of dictionaries
        self.web_session = web_session
        self.hubs = [TinxyLocalHub(node["ip_address"]) for node in nodes]
        self.device_polling_intervals = {node["device_id"]: 5 for node in nodes}  # Default 5 seconds
        self.device_metadata = {}  # Type-annotated as a dictionary

    async def _async_update_data(self):
        """Fetch data from each configured Tinxy node."""
        status_list = {}
        for hub, node in zip(self.hubs, self.nodes, strict=False):
            try:
                device_data = await hub.fetch_device_data(node, self.web_session)
                if device_data:
                    status_list[node["device_id"]] = device_data
                    # Populate device metadata for other information (firmware, model, etc.)
                    self.device_metadata[node["device_id"]] = {
                        "firmware": device_data.get("firmware", "Unknown"),
                        "model": device_data.get("model", "Tinxy Smart Device"),
                        "rssi": device_data.get("rssi"),
                        "ssid": device_data.get("ssid"),
                        "ip": device_data.get("ip"),
                        "version": device_data.get("version"),
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

        # Call the device registration method after the initial data fetch
        await self._register_devices()
        return status_list

    def set_polling_interval(self, device_id: str, interval: int) -> None:
        """Set the polling interval for a specific device."""
        _LOGGER.debug("Setting polling interval for device %s to %d seconds", device_id, interval)
        self.device_polling_intervals[device_id] = interval
        self.update_interval = timedelta(
            seconds=min(self.device_polling_intervals.values(), default=5)
        )

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
