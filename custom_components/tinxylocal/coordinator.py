"""Poll Tinxy devices over the local network."""

from __future__ import annotations

import logging
from datetime import timedelta

from tinxy import (
    DeviceStatus,
    Relay,
    TinxyError,
    TinxyLocalClient,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Bronze `runtime-data`: the coordinator lives on the entry, not in hass.data.
# It owns the clients, so it is the only thing the platforms need.
type TinxyConfigEntry = ConfigEntry[TinxyUpdateCoordinator]


class TinxyUpdateCoordinator(DataUpdateCoordinator[dict[str, DeviceStatus]]):
    """Keep one device's state fresh.

    `data` is keyed by device id and holds the library's `DeviceStatus`, which
    carries both the relay states and the device details the entities need, so
    there is no second metadata store to keep in step.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        nodes: list[dict],
        clients: list[TinxyLocalClient],
        polling_interval: int,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="Tinxy",
            config_entry=config_entry,
            update_interval=timedelta(seconds=polling_interval),
        )
        self.nodes = nodes
        # Shared with the platforms, so polling honours the configured timeout
        # and commands queue against the same per-device worker.
        self.clients = clients
        self._devices_registered = False

    def relays_for(self, node: dict) -> list[Relay]:
        """Return the relay names and types the owner configured in the app."""
        return [Relay(d["name"], d["type"]) for d in node["devices"]]

    async def _async_update_data(self) -> dict[str, DeviceStatus]:
        """Read every configured device."""
        statuses: dict[str, DeviceStatus] = {}
        errors: list[str] = []

        for client, node in zip(self.clients, self.nodes, strict=False):
            try:
                statuses[node["device_id"]] = await client.get_status(
                    self.relays_for(node)
                )
            except TinxyError as err:
                errors.append(f"{node['name']}: {err}")

        # A device that stops answering must mark its entities unavailable rather
        # than leave them showing the last state it happened to report.
        # DataUpdateCoordinator logs this once and keeps the previous data, so
        # entities fall back to `last_update_success` instead of stale values.
        if not statuses:
            raise UpdateFailed("; ".join(errors) or "No Tinxy device returned data")

        if not self._devices_registered:
            self._register_devices(statuses)
            self._devices_registered = True

        return statuses

    def _register_devices(self, statuses: dict[str, DeviceStatus]) -> None:
        """Add each device to the registry, once rather than on every poll."""
        registry = dr.async_get(self.hass)
        for node in self.nodes:
            status = statuses.get(node["device_id"])
            registry.async_get_or_create(
                config_entry_id=self.config_entry.entry_id,
                identifiers={(DOMAIN, node["device_id"])},
                name=node["name"],
                manufacturer="Tinxy",
                model=(status.model if status else None) or node.get("model"),
                # The library returns this as text; the device reports a number
                # and the registry rejects one.
                sw_version=status.firmware if status else None,
            )
