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
    device_data = entry.data["device"]
    device_types = device_data.get("deviceTypes", [])
    
    # Get features from typeId for more reliable device type detection
    type_id = device_data.get("typeId", {})
    features = type_id.get("features", [])
    
    for node in coordinator.nodes:
        node_name = node["name"]
        device_names = node.get("devices", [])
        
        # Handle empty devices array
        if not device_names:
            num_relays = type_id.get("numberOfRelays", 1)
            device_names = [device_types[i] if i < len(device_types) else f"Device {i+1}" for i in range(num_relays)]

        for index, device_name in enumerate(device_names):
            # Ensure device_name is a string, not a dict object
            if isinstance(device_name, dict):
                device_name_str = device_name.get("name", f"Device {index + 1}")
            else:
                device_name_str = str(device_name)
                
            # Use features array first (most reliable), then fall back to deviceTypes
            if index < len(features) and "FAN" in features[index]:
                device_type = "Fan"
            elif index < len(device_types):
                device_type = device_types[index]
            else:
                device_type = "Socket"
            
            # Only create fan entities for devices that actually have fan capabilities
            # IMPORTANT: Only trust the features array for hardware capabilities
            has_fan_feature = index < len(features) and "FAN" in features[index]
            if has_fan_feature:
                relay_number = index + 1
                entity_name = f"{node_name} {device_name_str}"
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
        if self.coordinator.data is None:
            return 0

        node_data = self.coordinator.data.get(self.node_id, {})
        if not node_data:
            return 0

        device_data = node_data.get("devices", [])

        if len(device_data) >= self.relay_number:
            device = device_data[self.relay_number - 1]
            brightness = device.get("brightness", 0)
            is_on = device.get("status") == "on"
            
            # If fan is off, return 0, otherwise return the brightness value
            return brightness if is_on else 0

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
            # If no percentage specified, try to use the last known brightness value
            if self.coordinator.data is not None:
                node_data = self.coordinator.data.get(self.node_id, {})
                if node_data:
                    device_data = node_data.get("devices", [])
                    if len(device_data) >= self.relay_number:
                        device = device_data[self.relay_number - 1]
                        stored_brightness = device.get("brightness", 0)
                        if stored_brightness > 0:
                            percentage = stored_brightness
            
            # If no stored brightness or it's 0, use medium speed as default
            if percentage is None or percentage == 0:
                percentage = 66  # Default to medium speed (66%)

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
