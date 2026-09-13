"""Fan platform for Tinxy integration."""

import logging
from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, ICONS
from tinxy import TinxyLocalClient, snap_to_speed_level

from .coordinator import TinxyConfigEntry, TinxyUpdateCoordinator
from .entity import TinxyOptimisticMixin

_LOGGER = logging.getLogger(__name__)

# Tinxy fans support 3 discrete speed levels: 33%, 66%, 100%
SPEED_LEVELS = [33, 66, 100]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TinxyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tinxy fans based on a config entry."""
    coordinator = entry.runtime_data
    clients = coordinator.clients

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
                fan = TinxyFan(
                    coordinator=coordinator,
                    client=clients[0],
                    node_id=node["device_id"],
                    relay_number=relay_number,
                    device_name=node_name,
                    name=device_name_str,
                    device_type=device_type,
                )
                fans.append(fan)

    async_add_entities(fans)


class TinxyFan(TinxyOptimisticMixin, CoordinatorEntity, FanEntity):
    """Representation of a Tinxy fan."""

    # Bronze `has-entity-name`: Home Assistant composes "<device> <entity>".
    _attr_has_entity_name = True

    _attr_supported_features = (
        FanEntityFeature.SET_SPEED
        | FanEntityFeature.TURN_OFF
        | FanEntityFeature.TURN_ON
    )

    def __init__(
        self,
        coordinator: TinxyUpdateCoordinator,
        client: TinxyLocalClient,
        node_id: str,
        relay_number: int,
        device_name: str,
        name: str,
        device_type: str,
    ) -> None:
        """Initialize the Tinxy fan."""
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.client = client
        self.node_id = node_id
        self.relay_number = relay_number
        self._attr_name = name
        self._device_name = device_name
        self._attr_unique_id = f"{node_id}_{relay_number}_fan"
        self._device_type = device_type
        self._attr_speed_count = len(SPEED_LEVELS)

    @property
    def unique_id(self) -> str:
        """Return a unique ID for the entity."""
        return self._attr_unique_id

    @property
    def available(self) -> bool:
        """Return True if the last poll succeeded and this device reported data."""
        return (
            self.coordinator.last_update_success
            and self.node_id in (self.coordinator.data or {})
        )

    @property
    def _status(self):
        """Return this device's last reported status, if any."""
        return (self.coordinator.data or {}).get(self.node_id)

    @property
    def _relay(self):
        """Return this entity's relay, if the device reported it."""
        status = self._status
        if status and len(status.relays) >= self.relay_number:
            return status.relays[self.relay_number - 1]
        return None

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return device information to associate entities with the device."""
        status = self._status
        return {
            "identifiers": {(DOMAIN, self.node_id)},
            "name": self._device_name,
            "manufacturer": "Tinxy",
            "model": status.model if status else None,
            "sw_version": status.firmware if status else None,
        }

    @property
    def is_on(self) -> bool | None:
        """Return True if the fan is on."""
        if self._optimistic is not None:
            return self._optimistic > 0

        relay = self._relay
        return relay.is_on if relay else False

    @property
    def percentage(self) -> int | None:
        """Return the current speed percentage."""
        if self._optimistic is not None:
            return self._optimistic

        relay = self._relay
        if not relay or not relay.is_on:
            return 0
        return relay.brightness or 0

    @property
    def icon(self) -> str:
        """Return the icon of the fan."""
        return ICONS.get(self._device_type, "mdi:fan")

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn the fan on."""
        if percentage is None:
            # If no percentage specified, try to use the last known brightness value
            relay = self._relay
            if relay and relay.brightness:
                percentage = relay.brightness
            
            # If no stored brightness or it's 0, use medium speed as default
            if percentage is None or percentage == 0:
                percentage = 66  # Default to medium speed (66%)

        await self.async_set_percentage(percentage)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the fan off."""
        await self._async_command(
            0,
            self.client.toggle(
                self.coordinator.nodes[0]["mqtt_password"],
                relay=self.relay_number,
                on=False,
            ),
        )

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the speed percentage of the fan."""
        if percentage == 0:
            await self.async_turn_off()
            return

        # The hardware only has three speeds; snap to the nearest.
        brightness = snap_to_speed_level(percentage)

        await self._async_command(
            brightness,
            self.client.set_brightness(
                self.coordinator.nodes[0]["mqtt_password"],
                relay=self.relay_number,
                brightness=brightness,
            ),
        )
