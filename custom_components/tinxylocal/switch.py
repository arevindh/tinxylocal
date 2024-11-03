"""Switch platform for Tinxy integration."""

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .hub import TinxyLocalHub

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Tinxy switches based on a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    hubs = hass.data[DOMAIN][entry.entry_id]["hubs"]

    # Retrieve the node configuration directly from the coordinator
    switches = []
    for node in coordinator.nodes:
        device_name = node["name"]
        for index, device in enumerate(node["devices"]):
            if device["type"].lower():
                # Adjust relay_number to start from 1 instead of 0
                relay_number = index + 1
                entity_name = f"{device_name} {device['name']}"
                switch = TinxySwitch(
                    coordinator=coordinator,
                    hub=hubs[0],
                    node_id=node["device_id"],
                    relay_number=relay_number,
                    name=entity_name,
                )
                switches.append(switch)

    async_add_entities(switches)


class TinxySwitch(CoordinatorEntity, SwitchEntity):
    """Representation of a Tinxy switch."""

    def __init__(
        self,
        coordinator,
        hub: TinxyLocalHub,
        node_id: str,
        relay_number: int,
        name: str,
    ):
        """Initialize the Tinxy switch."""
        super().__init__(coordinator)
        self.hub = hub
        self.node_id = node_id
        self.relay_number = relay_number
        self._attr_name = name
        self._attr_unique_id = f"{node_id}_{relay_number}"
        self._state = None

    @property
    def available(self):
        """Return True if the device status data is available and valid."""
        node_data = self.coordinator.data.get(self.node_id, {})
        return bool(node_data) and self.node_id in self.coordinator.device_metadata

    @property
    def device_info(self):
        """Return device information to associate entities with the device."""
        # Ensure device_info only accesses populated metadata
        metadata = self.coordinator.device_metadata.get(self.node_id, {})

        return {
            "identifiers": {(DOMAIN, self.node_id)},
            "name": self._attr_name.split(" ")[0],
            "manufacturer": "Tinxy",
            "model": metadata.get("model", "Tinxy Smart Device"),
            "sw_version": metadata.get("firmware", "Unknown"),
            "via_device": (DOMAIN, self.node_id),
            "connections": {(dr.CONNECTION_IP, metadata.get("ip"))}
            if metadata.get("ip")
            else None,
            "suggested_area": metadata.get("ssid"),
        }

    @property
    def is_on(self):
        """Return the status of the switch."""
        # Check if coordinator data is available and fetch data based on node_id
        if self.coordinator.data is None:
            _LOGGER.warning(
                "Coordinator data is not available for node %s", self._attr_unique_id
            )
            return False  # Default to off if data is not available

        node_data = self.coordinator.data.get(self.node_id, {})
        if not node_data:
            _LOGGER.warning("Node data is missing for node %s", self.node_id)
            return False

        # Access the device data within the node data
        device_data = node_data.get("devices", [])

        # Adjust for 1-based relay numbering
        if len(device_data) >= self.relay_number:
            return device_data[self.relay_number - 1].get("status") == "on"

        _LOGGER.warning(
            "Device data is unavailable for relay number %s in node %s",
            self.relay_number,
            self.node_id,
        )
        return False

    async def async_turn_on(self, **kwargs):
        """Turn the switch on."""
        result = await self.hub.tinxy_toggle(
            mqttpass=self.coordinator.nodes[0][
                "mqtt_password"
            ],  # Use the first node's MQTT password
            relay_number=self.relay_number,
            action=1,
            web_session=self.coordinator.hass.helpers.aiohttp_client.async_get_clientsession(),
        )
        if result:
            await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        result = await self.hub.tinxy_toggle(
            mqttpass=self.coordinator.nodes[0][
                "mqtt_password"
            ],  # Use the first node's MQTT password
            relay_number=self.relay_number,
            action=0,
            web_session=self.coordinator.hass.helpers.aiohttp_client.async_get_clientsession(),
        )
        if result:
            await self.coordinator.async_request_refresh()

    @property
    def available(self):
        """Return if entity is available."""
        return self.coordinator.last_update_success
