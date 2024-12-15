"""Number platform for Tinxy integration."""

from homeassistant.components.number import NumberEntity, RestoreNumber
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import TinxyUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Tinxy numbers based on a config entry."""
    coordinator: TinxyUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    # Create a number entity for each device's polling interval
    numbers = []
    for node in coordinator.nodes:
        entity_name = f"{node['name']} Polling Interval"
        number_entity = TinxyPollingNumber(
            coordinator=coordinator,
            device_id=node["device_id"],
            name=entity_name,
        )
        numbers.append(number_entity)

    async_add_entities(numbers)


class TinxyPollingNumber(RestoreNumber, NumberEntity):
    """Representation of a polling interval for a Tinxy device."""

    def __init__(self, coordinator: TinxyUpdateCoordinator, device_id: str, name: str) -> None:
        """Initialize the number entity."""
        self._coordinator = coordinator
        self._device_id = device_id
        self._attr_name = name
        self._attr_unique_id = f"{device_id}_polling_interval"
        self._attr_native_min_value = 1  # Minimum interval in seconds
        self._attr_native_max_value = 600  # Maximum interval in seconds
        self._attr_native_step = 1  # Increment step
        self._attr_native_value = 5  # Default polling interval in seconds

    @property
    def device_info(self):
        """Return device registry information to associate entity with a device."""
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "manufacturer": "Tinxy",
            "model": "Tinxy Smart Device",
        }

    @property
    def available(self) -> bool:
        """Ensure the polling interval number entity is always available."""
        return True

    async def async_set_native_value(self, value: float) -> None:
        """Set the polling interval."""
        self._attr_native_value = value
        self._coordinator.set_polling_interval(self._device_id, int(value))
        await self._coordinator.async_request_refresh()

    async def async_added_to_hass(self) -> None:
        """Restore previous state on Home Assistant restart."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_number_data()) is not None:
            if last_state.native_value is not None:  # Ensure the value is not None
                self._attr_native_value = last_state.native_value
                self._coordinator.set_polling_interval(self._device_id, int(last_state.native_value))
            else:
                # Default to current attribute value if no previous state is available
                self._coordinator.set_polling_interval(self._device_id, int(self._attr_native_value))