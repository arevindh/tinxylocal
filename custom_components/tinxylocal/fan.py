"""Fan platform for Tinxy integration."""

import asyncio
import logging
from typing import Any, cast

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import TinxyUpdateCoordinator
from .hub import TinxyLocalHub

_LOGGER = logging.getLogger(__name__)

# Tinxy fans support 3 discrete speed levels: 33%, 66%, 100%
SPEED_LEVELS = [33, 66, 100]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Tinxy fans based on a config entry."""
    coordinator = cast(
        TinxyUpdateCoordinator, hass.data[DOMAIN][entry.entry_id]["coordinator"]
    )
    hubs = hass.data[DOMAIN][entry.entry_id]["hubs"]

    # Skip creating fans if this is a lock device
    device_data = entry.data["device"]
    if device_data.get("typeId", {}).get("gtype") == "action.devices.types.LOCK":
        async_add_entities([])
        return

    fans = []
    device_types = entry.data["device"].get("deviceTypes", [])
    for node in coordinator.nodes:
        device_name = node["name"]

        for index, device in enumerate(node["devices"]):
            device_type = (
                device_types[index] if index < len(device_types) else "Socket"
            )
            
            # Only create fan entities for fan devices that support local control
            # RF-based devices don't support local brightness control
            if device_type.lower() == "fan" and device["type"].lower():
                relay_number = index + 1
                entity_name = f"{device_name} {device['name']}"
                fan = TinxyFan(
                    coordinator=coordinator,
                    hub=hubs[0],
                    node_id=node["device_id"],
                    relay_number=relay_number,
                    name=entity_name,
                    device_type=device_type,
                )
                fans.append(fan)

    async_add_entities(fans)


class TinxyFan(CoordinatorEntity, FanEntity):
    """Representation of a Tinxy fan."""

    _attr_supported_features = (
        FanEntityFeature.SET_SPEED
        | FanEntityFeature.TURN_OFF
        | FanEntityFeature.TURN_ON
    )

    def __init__(
        self,
        coordinator: TinxyUpdateCoordinator,
        hub: TinxyLocalHub,
        node_id: str,
        relay_number: int,
        name: str,
        device_type: str,
    ) -> None:
        """Initialize the Tinxy fan."""
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.hub = hub
        self.node_id = node_id
        self.relay_number = relay_number
        self._attr_name = name
        self._attr_unique_id = f"{node_id}_{relay_number}_fan"
        self._device_type = device_type
        self._attr_speed_count = len(SPEED_LEVELS)

    @property
    def unique_id(self) -> str:
        """Return a unique ID for the entity."""
        return self._attr_unique_id

    @property
    def available(self) -> bool:
        """Return True if the device status data is available and valid."""
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
        """Return True if the fan is on."""
        if self.coordinator.data is None:
            _LOGGER.debug(
                "Coordinator data is not available for node %s", self._attr_unique_id
            )
            return False

        node_data = self.coordinator.data.get(self.node_id, {})
        if not node_data:
            _LOGGER.debug("Node data is missing for node %s", self.node_id)
            return False

        device_data = node_data.get("devices", [])

        if len(device_data) >= self.relay_number:
            return device_data[self.relay_number - 1].get("status") == "on"

        _LOGGER.debug(
            "Device data is unavailable for relay number %s in node %s",
            self.relay_number,
            self.node_id,
        )
        return False

    @property
    def percentage(self) -> int | None:
        """Return the current speed percentage."""
        if not self.is_on:
            return 0

        if self.coordinator.data is None:
            return 0

        node_data = self.coordinator.data.get(self.node_id, {})
        if not node_data:
            return 0

        device_data = node_data.get("devices", [])

        if len(device_data) >= self.relay_number:
            device = device_data[self.relay_number - 1]
            brightness = device.get("brightness", 0)
            # Return the actual brightness value since it's already a percentage
            return brightness

        return 0

    @property
    def icon(self) -> str:
        """Return the icon of the fan."""
        return self.hub.get_device_icon(self._device_type)

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn the fan on."""
        if percentage is None:
            # If no percentage specified, turn on at current speed or medium speed
            current_percentage = self.percentage
            if current_percentage and current_percentage > 0:
                percentage = current_percentage
            else:
                percentage = 50  # Default to medium speed

        await self.async_set_percentage(percentage)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the fan off."""
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
            _LOGGER.error("Failed to turn off fan %s: %s", self.node_id, e)

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the speed percentage of the fan."""
        if percentage == 0:
            await self.async_turn_off()
            return

        # Map percentage to the nearest discrete speed level
        if percentage <= 33:
            brightness = 33
        elif percentage <= 66:
            brightness = 66
        else:
            brightness = 100
        
        # Set the brightness/speed using the CLI (this will also turn on the fan)
        result = await self._set_brightness(brightness)
        
        if result:
            await asyncio.sleep(0.5)
            await self.coordinator.async_request_refresh()

    async def _set_brightness(self, brightness: int) -> bool:
        """Set the brightness/speed of the fan using CLI."""
        try:
            return await self.hub.queue_brightness_command(
                self.node_id,
                self.coordinator.nodes[0]["mqtt_password"],
                self.relay_number,
                brightness,
            )
        except Exception as e:
            _LOGGER.error("Failed to set brightness for fan %s: %s", self.node_id, e)
            return False
