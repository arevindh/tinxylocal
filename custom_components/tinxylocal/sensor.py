"""Diagnostic sensor platform for Tinxy integration.

The RSSI/SSID/IP sensor set comes from the ha-tinxylocal fork by @selvakk2k,
collapsed here into one description-driven class and with RSSI disabled by
default, since it changes on nearly every poll and fills the recorder database.

Every value comes from the `DeviceStatus` the coordinator already fetches, so
these cost no extra requests.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import TinxyConfigEntry, TinxyUpdateCoordinator


@dataclass(frozen=True, kw_only=True)
class TinxySensorDescription(SensorEntityDescription):
    """Describes a Tinxy diagnostic sensor and how to read it from metadata."""

    value_fn: Callable[[Any], Any]


SENSORS: tuple[TinxySensorDescription, ...] = (
    TinxySensorDescription(
        key="rssi",
        name="Wi-Fi signal",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        entity_registry_enabled_default=False,
        value_fn=lambda status: status.rssi,
    ),
    TinxySensorDescription(
        key="ssid",
        name="Wi-Fi network",
        value_fn=lambda status: status.ssid,
    ),
    TinxySensorDescription(
        key="ip",
        name="IP address",
        value_fn=lambda status: status.ip,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TinxyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tinxy diagnostic sensors based on a config entry."""
    coordinator = entry.runtime_data

    async_add_entities(
        TinxyDiagnosticSensor(coordinator, node, description)
        for node in coordinator.nodes
        for description in SENSORS
    )


class TinxyDiagnosticSensor(CoordinatorEntity, SensorEntity):
    """A read-only detail about the device itself rather than one of its relays."""

    entity_description: TinxySensorDescription
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TinxyUpdateCoordinator,
        node: dict[str, Any],
        description: TinxySensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self.node_id = node["device_id"]
        self._node_name = node["name"]
        self._attr_unique_id = f"{self.node_id}_{description.key}"

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
    def device_info(self) -> DeviceInfo:
        """Attach to the same device the switches and fans belong to."""
        status = self._status
        return DeviceInfo(
            identifiers={(DOMAIN, self.node_id)},
            name=self._node_name,
            manufacturer="Tinxy",
            model=status.model if status else None,
            sw_version=status.firmware if status else None,
        )

    @property
    def native_value(self) -> Any:
        """Return the current value."""
        status = self._status
        return self.entity_description.value_fn(status) if status else None
