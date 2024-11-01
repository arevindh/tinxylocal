"""Tinxy Node Update Coordinator."""

import asyncio
from datetime import timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .hub import TinxyConnectionException, TinxyLocalException, TinxyLocalHub

_LOGGER = logging.getLogger(__name__)
REQUEST_REFRESH_DELAY = 0.50


class TinxyUpdateCoordinator(DataUpdateCoordinator):
    """Coordinator to fetch data directly from Tinxy nodes."""

    def __init__(self, hass: HomeAssistant, nodes: list[dict], web_session) -> None:
        """Initialize the Tinxy Update Coordinator with node configurations and session."""
        super().__init__(
            hass,
            _LOGGER,
            name="Tinxy Nodes",
            update_interval=timedelta(seconds=5),
            request_refresh_debouncer=Debouncer(
                hass, _LOGGER, cooldown=REQUEST_REFRESH_DELAY, immediate=False
            ),
        )
        self.hass = hass
        self.nodes = nodes  # List of nodes with their config details
        self.web_session = web_session
        self.hubs = [TinxyLocalHub(node["ip_address"]) for node in nodes]

    async def _async_update_data(self):
        """Fetch data from each configured Tinxy node."""
        status_list = {}
        try:
            async with asyncio.timeout(10):
                for hub, node in zip(self.hubs, self.nodes, strict=False):
                    try:
                        # Fetch data from the node using the hub instance
                        device_data = await hub.fetch_device_data(
                            node, self.web_session
                        )
                        if device_data:
                            # Use the node's device_id as the key in the status_list
                            status_list[node["device_id"]] = device_data
                    except TinxyConnectionException as conn_err:
                        _LOGGER.error(
                            "Connection error for node %s: %s", node["name"], conn_err
                        )
                        continue
                    except TinxyLocalException as node_err:
                        _LOGGER.error(
                            "Error communicating with node %s: %s",
                            node["name"],
                            node_err,
                        )
                        continue

                # Update the coordinator's data with status_list
                return status_list
        except TinxyLocalException as err:
            raise UpdateFailed(f"Error updating from Tinxy nodes: {err}") from err
