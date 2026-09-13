"""Switch platform for Tinxy integration."""

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity


from .const import DOMAIN, ICONS
from tinxy import TinxyLocalClient

from .coordinator import TinxyConfigEntry, TinxyUpdateCoordinator
from .entity import TinxyOptimisticMixin

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TinxyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tinxy switches based on a config entry."""
    coordinator = entry.runtime_data
    clients = coordinator.clients

    # Skip creating switches if this is a lock device
    device_data = entry.data["device"]
    if device_data.get("typeId", {}).get("gtype") == "action.devices.types.LOCK":
        async_add_entities([])
        return

    switches = []
    device_data = entry.data["device"]
    device_types = device_data.get("deviceTypes", [])
    
    # Get features from typeId for more reliable device type detection
    type_id = device_data.get("typeId", {})
    features = type_id.get("features", [])
    
    for node in coordinator.nodes:
        device_name = node["name"]

        for index, device in enumerate(node["devices"]):
            # Ensure device is a string (device name), not a dict object
            if isinstance(device, dict):
                device_name_str = device.get("name", f"Device {index + 1}")
            else:
                device_name_str = str(device)
            
            # Use features array first (most reliable), then fall back to deviceTypes
            if index < len(features) and "FAN" in features[index]:
                device_type = "Fan"
            elif index < len(device_types):
                device_type = device_types[index]
            else:
                device_type = "Socket"
            
            # Skip fan devices ONLY if they actually have fan hardware capabilities
            # Check features array, not deviceTypes (which is user configuration)
            has_fan_feature = index < len(features) and "FAN" in features[index]
            if has_fan_feature:
                continue
                
            relay_number = index + 1
            
            switch = TinxySwitch(
                coordinator=coordinator,
                client=clients[0],
                node_id=node["device_id"],
                relay_number=relay_number,
                device_name=device_name,
                name=device_name_str,
                device_type=device_type,
            )
            switches.append(switch)

    async_add_entities(switches)


class TinxySwitch(TinxyOptimisticMixin, CoordinatorEntity, SwitchEntity):
    """Representation of a Tinxy switch."""

    # Bronze `has-entity-name`: Home Assistant composes "<device> <entity>", so
    # `name` here is the relay's own label only.
    _attr_has_entity_name = True

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
        """Initialize the Tinxy switch."""
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.client = client
        self.node_id = node_id
        self.relay_number = relay_number
        self._attr_name = name
        self._device_name = device_name
        self._attr_unique_id = f"{node_id}_{relay_number}"
        self._device_type = device_type

    @property
    def unique_id(self) -> str:
        """Return a unique ID for the entity."""
        return self._attr_unique_id

    @property
    def available(self) -> bool:
        """Return True if the last poll succeeded and this device reported data."""
        # `last_update_success` is what goes false when the device stops answering;
        # without it the entity would keep serving the last state it ever saw.
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
        """Return the status of the switch."""
        if self._optimistic is not None:
            return self._optimistic

        relay = self._relay
        return relay.is_on if relay else False

    @property
    def icon(self) -> str:
        """Return the icon of the switch."""
        return ICONS.get(self._device_type, "mdi:toggle-switch")

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self._async_command(
            True,
            self.client.toggle(
                self.coordinator.nodes[0]["mqtt_password"],
                relay=self.relay_number,
                on=True,
            ),
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self._async_command(
            False,
            self.client.toggle(
                self.coordinator.nodes[0]["mqtt_password"],
                relay=self.relay_number,
                on=False,
            ),
        )
