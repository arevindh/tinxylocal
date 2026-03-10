"""Diagnostic sensor platform for Tinxy integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, cast

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfSignalStrength
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import TinxyUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class TinxySensorEntityDescription(SensorEntityDescription):
    """Describes a Tinxy diagnostic sensor."""

    metadata_key: str = ""


DIAGNOSTIC_SENSORS: tuple[TinxySensorEntityDescription, ...] = (
    TinxySensorEntityDescription(
        key="rssi",
        metadata_key="rssi",
        name="Signal Strength",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=UnitOfSignalStrength.DECIBELS_MILLIWATT,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:wifi",
    ),
    TinxySensorEntityDescription(
        key="ip",
        metadata_key="ip",
        name="IP Address",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:ip-network",
    ),
    TinxySensorEntityDescription(
        key="ssid",
        metadata_key="ssid",
        name="SSID",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:wifi",
    ),
    TinxySensorEntityDescription(
        key="firmware",
        metadata_key="firmware",
        name="Firmware",
        device_class=SensorDeviceClass.FIRMWARE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Tinxy diagnostic sensors from a config entry."""
    coordinator = cast(
        TinxyUpdateCoordinator, hass.data[DOMAIN][entry.entry_id]["coordinator"]
    )

    entities: list[TinxyDiagnosticSensor] = [
        TinxyDiagnosticSensor(coordinator, node, description)
        for node in coordinator.nodes
        for description in DIAGNOSTIC_SENSORS
    ]

    async_add_entities(entities)


class TinxyDiagnosticSensor(CoordinatorEntity, SensorEntity):
    """A diagnostic sensor for a Tinxy node (RSSI, IP, SSID, Firmware)."""

    entity_description: TinxySensorEntityDescription

    def __init__(
        self,
        coordinator: TinxyUpdateCoordinator,
        node: dict[str, Any],
        description: TinxySensorEntityDescription,
    ) -> None:
        """Initialize the diagnostic sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._node = node
        self._node_id = node["device_id"]
        self._attr_unique_id = f"{self._node_id}_{description.key}"
        self._attr_name = f"{node['name']} {description.name}"

    @property
    def available(self) -> bool:
        """Return True when coordinator has data for this node."""
        return (
            self.coordinator.data is not None
            and self._node_id in self.coordinator.device_metadata
        )

    @property
    def native_value(self) -> Any:
        """Return the sensor value from device metadata."""
        metadata = self.coordinator.device_metadata.get(self._node_id, {})
        return metadata.get(self.entity_description.metadata_key)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information to associate this sensor with its device."""
        metadata = self.coordinator.device_metadata.get(self._node_id, {})
        return DeviceInfo(
            identifiers={(DOMAIN, self._node_id)},
            name=self._node["name"],
            manufacturer="Tinxy",
            model=metadata.get("model", "Smart Device"),
            sw_version=metadata.get("firmware", "Unknown"),
        )
