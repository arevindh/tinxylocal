"""Lock platform for Tinxy integration."""

import logging
from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from tinxy import TinxyLocalClient

from .coordinator import TinxyConfigEntry, TinxyUpdateCoordinator
from .entity import TinxyOptimisticMixin

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TinxyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tinxy locks based on a config entry."""
    coordinator = entry.runtime_data
    clients = coordinator.clients

    locks = []
    device_data = entry.data["device"]
    
    # Check if this is a lock device based on the typeId
    if device_data.get("typeId", {}).get("gtype") == "action.devices.types.LOCK":
        for node in coordinator.nodes:
            # For lock devices, create a single lock entity
            lock = TinxyLock(
                coordinator=coordinator,
                client=clients[0],
                node_id=node["device_id"],
                relay_number=1,  # Locks typically use relay 1
                device_name=node["name"],
                device_data=device_data,
            )
            locks.append(lock)

    async_add_entities(locks)


class TinxyLock(TinxyOptimisticMixin, CoordinatorEntity, LockEntity):
    """Representation of a Tinxy lock."""

    # Bronze `has-entity-name`. The lock is the device's only entity, so it takes
    # the device's own name: `_attr_name = None` is how HA expresses that.
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(
        self,
        coordinator: TinxyUpdateCoordinator,
        client: TinxyLocalClient,
        node_id: str,
        relay_number: int,
        device_name: str,
        device_data: dict,
    ) -> None:
        """Initialize the Tinxy lock."""
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.client = client
        self.node_id = node_id
        self.relay_number = relay_number
        self._device_name = device_name
        self._attr_unique_id = f"{node_id}_lock"
        self._device_data = device_data
        self._attr_supported_features = 0  # Basic lock/unlock only

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
            "model": self._device_data.get("typeId", {}).get("long_name", "Smart Lock"),
            "sw_version": status.firmware if status else None,
        }

    @property
    def is_locked(self) -> bool | None:
        """Return True if the lock is locked.

        A pulse relay has no lock state to read back. The firmware reports a
        `door` field on units that have the sensor, which is authoritative when
        present; otherwise an idle relay is taken to mean locked.
        """
        if self._optimistic == "unlocking":
            return False

        status = self._status
        if status is None:
            return True

        if status.door == "OPEN":
            return False

        relay = self._relay
        return relay.is_on is False if relay else True

    @property
    def is_unlocking(self) -> bool:
        """Return True while the unlock pulse is in flight."""
        return self._optimistic == "unlocking"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose the door sensor where the device has one."""
        status = self._status
        if status and status.door:
            return {"door_status": status.door}
        return None

    @property
    def icon(self) -> str:
        """Return the icon of the lock."""
        status = self._status
        if status and status.door == "OPEN":
            return "mdi:door-open"
        return "mdi:lock" if self.is_locked else "mdi:lock-open"

    async def async_lock(self, **kwargs: Any) -> None:
        """Lock the device."""
        # For most door locks, there's no explicit "lock" command
        # The lock automatically locks after a timeout
        # This method exists for Home Assistant compatibility but may not do anything
        _LOGGER.info(
            "Lock command sent to %s (may not be supported by device)", self._device_name
        )

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the device."""
        # For pulse switches, we send a pulse (action=1) to unlock.
        # The lock will automatically lock again after its configured timeout.
        await self._async_command(
            "unlocking",
            self.client.toggle(
                self.coordinator.nodes[0]["mqtt_password"],
                relay=self.relay_number,
                on=True,
            ),
        )
