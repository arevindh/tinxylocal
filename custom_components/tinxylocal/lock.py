"""Lock platform for Tinxy integration."""

import asyncio
import logging
from typing import Any, cast

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
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
    """Set up Tinxy locks based on a config entry."""
    coordinator = cast(
        TinxyUpdateCoordinator, hass.data[DOMAIN][entry.entry_id]["coordinator"]
    )
    hubs = hass.data[DOMAIN][entry.entry_id]["hubs"]

    locks = []
    device_data = entry.data["device"]
    
    # Check if this is a lock device based on the typeId
    if device_data.get("typeId", {}).get("gtype") == "action.devices.types.LOCK":
        for node in coordinator.nodes:
            device_name = node["name"]
            # For lock devices, create a single lock entity
            lock = TinxyLock(
                coordinator=coordinator,
                hub=hubs[0],
                node_id=node["device_id"],
                relay_number=1,  # Locks typically use relay 1
                name=device_name,
                device_data=device_data,
            )
            locks.append(lock)

    async_add_entities(locks)


class TinxyLock(CoordinatorEntity, LockEntity):
    """Representation of a Tinxy lock."""

    def __init__(
        self,
        coordinator: TinxyUpdateCoordinator,
        hub: TinxyLocalHub,
        node_id: str,
        relay_number: int,
        name: str,
        device_data: dict,
    ) -> None:
        """Initialize the Tinxy lock."""
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.hub = hub
        self.node_id = node_id
        self.relay_number = relay_number
        self._attr_name = name
        self._attr_unique_id = f"{node_id}_lock"
        self._device_data = device_data
        self._attr_supported_features = 0  # Basic lock/unlock only

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
        
        return {
            "identifiers": {(DOMAIN, self.node_id)},
            "name": self._attr_name,
            "manufacturer": "Tinxy",
            "model": self._device_data.get("typeId", {}).get("long_name", "Smart Lock"),
            "sw_version": metadata.get("firmware", str(self._device_data.get("firmwareVersion", "Unknown"))),
        }

    @property
    def is_locked(self) -> bool | None:
        """Return True if the lock is locked."""
        # For pulse switches (like door locks), determining lock state is challenging
        # since they don't maintain state like regular switches.
        # We'll use a simple approach: assume the lock is locked by default
        # and only show as unlocked briefly after an unlock command.
        
        if self.coordinator.data is None:
            _LOGGER.debug(
                "Coordinator data is not available for node %s", self._attr_unique_id
            )
            return True  # Default to locked when no data

        node_data = self.coordinator.data.get(self.node_id, {})
        if not node_data:
            _LOGGER.debug("Node data is missing for node %s", self.node_id)
            return True  # Default to locked when no data

        # For locks without individual devices, check if there's any device data
        device_data = node_data.get("devices", [])
        if not device_data:
            # No device data available, assume locked
            return True
            
        if len(device_data) >= self.relay_number:
            status = device_data[self.relay_number - 1].get("status", "off")
            # For pulse switches: "on" might indicate recently activated (unlocked)
            # "off" indicates idle state (locked)
            return status == "off"

        # Default to locked if we can't determine state
        return True

    @property
    def icon(self) -> str:
        """Return the icon of the lock."""
        return "mdi:lock" if self.is_locked else "mdi:lock-open"

    async def async_lock(self, **kwargs: Any) -> None:
        """Lock the device."""
        # For most door locks, there's no explicit "lock" command
        # The lock automatically locks after a timeout
        # This method exists for Home Assistant compatibility but may not do anything
        _LOGGER.info("Lock command sent to %s (may not be supported by device)", self._attr_name)

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the device."""
        # For pulse switches, we send a pulse (action=1) to unlock
        # The lock will automatically lock again after its configured timeout
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
            _LOGGER.error("Failed to unlock device %s: %s", self.node_id, e)
