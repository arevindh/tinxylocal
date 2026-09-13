"""Diagnostic sensor platform for Tinxy integration.

The RSSI/SSID/IP sensor set comes from the ha-tinxylocal fork by @selvakk2k,
collapsed here into one description-driven class and with RSSI disabled by
default, since it changes on nearly every poll and fills the recorder database.

Everything here is read straight out of `coordinator.device_metadata`, which the
coordinator already fills on every poll from the device's `/info` response.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import TinxyUpdateCoordinator


@dataclass(frozen=True, kw_only=True)
class TinxySensorDescription(SensorEntityDescription):
    """Describes a Tinxy diagnostic sensor and how to read it from metadata."""

    value_fn: Callable[[dict[str, Any]], Any]


SENSORS: tuple[TinxySensorDescription, ...] = (
    TinxySensorDescription(
        key="rssi",
        name="Wi-Fi signal",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        entity_registry_enabled_default=False,
        value_fn=lambda metadata: metadata.get("rssi"),
    ),
    TinxySensorDescription(
        key="ssid",
        name="Wi-Fi network",
        value_fn=lambda metadata: metadata.get("ssid"),
    ),
    TinxySensorDescription(
        key="ip",
        name="IP address",
        value_fn=lambda metadata: metadata.get("ip"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Tinxy diagnostic sensors based on a config entry."""
    coordinator = cast(
        TinxyUpdateCoordinator, hass.data[DOMAIN][entry.entry_id]["coordinator"]
    )

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
        """Return True if the last poll succeeded and this node reported data."""
        return (
            self.coordinator.last_update_success
            and self.node_id in self.coordinator.device_metadata
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Attach to the same device the switches and fans belong to."""
        metadata = self.coordinator.device_metadata.get(self.node_id, {})
        return DeviceInfo(
            identifiers={(DOMAIN, self.node_id)},
            name=self._node_name,
            manufacturer="Tinxy",
            model=metadata.get("model", "Smart Device"),
            sw_version=metadata.get("firmware", "Unknown"),
        )

    @property
    def native_value(self) -> Any:
        """Return the current value."""
        return self.entity_description.value_fn(
            self.coordinator.device_metadata.get(self.node_id, {})
        )
