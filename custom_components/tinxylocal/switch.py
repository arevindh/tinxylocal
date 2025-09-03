"""Switch platform for Tinxy integration."""

import asyncio
import logging
from typing import Any, cast

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity


from .const import DOMAIN
from .coordinator import TinxyUpdateCoordinator
from .hub import TinxyLocalHub

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Tinxy switches based on a config entry."""
    coordinator = cast(
        TinxyUpdateCoordinator, hass.data[DOMAIN][entry.entry_id]["coordinator"]
    )
    hubs = hass.data[DOMAIN][entry.entry_id]["hubs"]

    # Skip creating switches if this is a lock device
    device_data = entry.data["device"]
    if device_data.get("typeId", {}).get("gtype") == "action.devices.types.LOCK":
        async_add_entities([])
        return

    switches = []
    device_types = entry.data["device"].get("deviceTypes", [])
    for node in coordinator.nodes:
        device_name = node["name"]

        for index, device in enumerate(node["devices"]):
            if device["type"].lower():
                relay_number = index + 1
                entity_name = f"{device_name} {device['name']}"
                device_type = (
                    device_types[index] if index < len(device_types) else "Socket"
                )
                
                # Skip fan devices as they will be handled by the fan platform
                # Note: Dimmable lights are RF-based and don't support local control
                if device_type.lower() == "fan":
                    continue
                    
                switch = TinxySwitch(
                    coordinator=coordinator,
                    hub=hubs[0],
                    node_id=node["device_id"],
                    relay_number=relay_number,
                    name=entity_name,
                    device_type=device_type,
                )
                switches.append(switch)

    async_add_entities(switches)


class TinxySwitch(CoordinatorEntity, SwitchEntity):
    """Representation of a Tinxy switch."""

    def __init__(
        self,
        coordinator: TinxyUpdateCoordinator,
        hub: TinxyLocalHub,
        node_id: str,
        relay_number: int,
        name: str,
        device_type: str,
    ) -> None:
        """Initialize the Tinxy switch."""
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.hub = hub
        self.node_id = node_id
        self.relay_number = relay_number
        self._attr_name = name
        self._attr_unique_id = f"{node_id}_{relay_number}"
        self._device_type = device_type

    @property
    def unique_id(self) -> str:
        """Return a unique ID for the entity."""
        return self._attr_unique_id

    @property
    def available(self) -> bool:
        """Return True if the device status data is available and valid."""
        # Return False if coordinator data is None to handle cases where data has not yet loaded
        if self.coordinator.data is None:
            _LOGGER.debug(
                "Coordinator data is not yet available for node %s", self.node_id
            )
            return False

        node_data = self.coordinator.data.get(self.node_id, {})
        return bool(node_data) and self.node_id in self.coordinator.device_metadata

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return device information to associate entities with the device."""
        metadata = self.coordinator.device_metadata.get(self.node_id, {})
        device_name = (
            self._attr_name.split(" ")[0] if self._attr_name else "Unknown Device"
        )

        return {
            "identifiers": {(DOMAIN, self.node_id)},
            "name": device_name,
            "manufacturer": "Tinxy",
            "model": metadata.get("model", "Smart Device"),
            "sw_version": metadata.get("firmware", "Unknown"),
        }

    @property
    def is_on(self) -> bool | None:
        """Return the status of the switch."""
        # Check if coordinator data is available and fetch data based on node_id
        if self.coordinator.data is None:
            _LOGGER.debug(
                "Coordinator data is not available for node %s", self._attr_unique_id
            )
            return False  # Default to off if data is not available

        node_data = self.coordinator.data.get(self.node_id, {})
        if not node_data:
            _LOGGER.debug("Node data is missing for node %s", self.node_id)
            return False

        # Access the device data within the node data
        device_data = node_data.get("devices", [])

        # Adjust for 1-based relay numbering
        if len(device_data) >= self.relay_number:
            return device_data[self.relay_number - 1].get("status") == "on"

        _LOGGER.debug(
            "Device data is unavailable for relay number %s in node %s",
            self.relay_number,
            self.node_id,
        )
        return False

    @property
    def icon(self) -> str:
        """Return the icon of the switch."""
        return self.hub.get_device_icon(self._device_type)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        try:
            result = await self.hub.queue_toggle_command(
                self.node_id,
                self.coordinator.nodes[0]["mqtt_password"],
                self.relay_number,
                1,
            )
            if result:
                await asyncio.sleep(0.5)
                await self.coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error("Failed to turn on switch %s: %s", self.node_id, e)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        try:
            result = await self.hub.queue_toggle_command(
                self.node_id,
                self.coordinator.nodes[0]["mqtt_password"],
                self.relay_number,
                0,
            )
            if result:
                await asyncio.sleep(0.5)
                await self.coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error("Failed to turn off switch %s: %s", self.node_id, e)
