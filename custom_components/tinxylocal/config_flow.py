"""Config flow for Tinxy Local integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY, CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_DEVICE, CONF_DEVICE_ID, CONF_MQTT_PASS, DOMAIN, TINXY_BACKEND
from .hub import TinxyLocalHub
from .tinxycloud import TinxyCloud, TinxyHostConfiguration

_LOGGER = logging.getLogger(__name__)

# Schema for entering a new API key
STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_KEY): str,
    }
)

# Simplified schema for choosing to use an existing token or enter a new one
STEP_CHOOSE_TOKEN_SCHEMA = vol.Schema(
    {
        vol.Required("token_choice"): vol.In(
            {
                "existing": "Use existing API token",
                "new": "Enter a new API token",
            }
        )
    }
)

# Schema for entering device IP and selecting a device
STEP_DEVICE_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_DEVICE_ID): str,
    }
)


async def validate_device(hass: HomeAssistant, host_ip, chip_id) -> dict[str, Any]:
    """Validate the device IP and selected device."""
    web_session = async_get_clientsession(hass)
    hub = TinxyLocalHub(host_ip)
    return hub.validate_ip(web_session, host_ip, chip_id)


async def read_devices(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Read Device List."""
    web_session = async_get_clientsession(hass)
    _LOGGER.info(data)

    host_config = TinxyHostConfiguration(
        api_token=data[CONF_API_KEY], api_url=TINXY_BACKEND
    )
    api = TinxyCloud(host_config=host_config, web_session=web_session)

    return await api.get_device_list()


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the API key and fetch device list."""
    web_session = async_get_clientsession(hass)
    hub = TinxyLocalHub(TINXY_BACKEND)

    if not await hub.authenticate(data[CONF_API_KEY], web_session):
        raise InvalidAuth

    return {"title": "Tinxy.in"}


def find_device_by_id(devicelist, target_id):
    """Find device by its ID in the list."""
    for device in devicelist:
        if device["_id"] == target_id:
            return device
    return None


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tinxy Local."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self.api_token = None
        self.cloud_devices = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step, checking for saved token or requesting it."""
        errors: dict[str, str] = {}

        # Check for an existing token in any active config entries
        for entry in self._async_current_entries():
            if CONF_API_KEY in entry.data:
                self.api_token = entry.data[CONF_API_KEY]
                break

        # If a token exists, present a choice to use it or enter a new one
        if self.api_token and user_input is None:
            return self.async_show_form(
                step_id="choose_token",
                data_schema=STEP_CHOOSE_TOKEN_SCHEMA,
            )

        # If the user chooses to use the existing token, proceed to device selection
        if user_input and "token_choice" in user_input:
            if user_input["token_choice"] == "existing":
                return await self.async_step_select_device()

            # If the user chooses to enter a new token, proceed to API key entry
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
            )

        # Handle API key submission
        if user_input and CONF_API_KEY in user_input:
            try:
                # Validate API key and save it
                await validate_input(self.hass, user_input)
                self.api_token = user_input[CONF_API_KEY]

                # Proceed to device selection with the new token
                return await self.async_step_select_device()

            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception during validation")
                errors["base"] = "unknown"

        # Show API key entry form if no token exists
        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_choose_token(
        self, user_input: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Handle the step where user chooses to use the existing token or enter a new one."""
        if user_input["token_choice"] == "existing":
            return await self.async_step_select_device()
        return self.async_show_form(step_id="user", data_schema=STEP_USER_DATA_SCHEMA)

    async def async_step_select_device(
        self, user_input: dict[str, Any] = None
    ) -> config_entries.ConfigFlowResult:
        """Select a device from cloud devices and configure IP."""
        errors = {}

        # Fetch devices from cloud using saved or new API key if not already fetched
        if not self.cloud_devices:
            self.cloud_devices = await read_devices(
                self.hass, {CONF_API_KEY: self.api_token}
            )

        # Build the selection schema
        device_options = {
            item["_id"]: "{} ({})".format(item["name"], item["uuidRef"]["uuid"])
            for item in self.cloud_devices
            if "mqttPassword" in item
            and "uuidRef" in item
            and "uuid" in item["uuidRef"]
        }

        if user_input:
            try:
                selected_device = find_device_by_id(
                    self.cloud_devices, user_input[CONF_DEVICE_ID]
                )

                if not selected_device:
                    raise ValueError("Device not found")  # noqa: TRY301

                web_session = async_get_clientsession(self.hass)
                hub = TinxyLocalHub(user_input[CONF_HOST])
                validate_status = await hub.validate_ip(
                    web_session,
                    selected_device["uuidRef"]["uuid"],
                )

                _LOGGER.debug("Device selection status: %s", validate_status)

                if validate_status == "wrong_chip_id":
                    raise ValueError(  # noqa: TRY301
                        "Wrong Ip address, chip id should be {}".format(
                            selected_device["uuidRef"]["uuid"]
                        )
                    )

                if validate_status == "api_not_available":
                    raise ValueError("Local API not available.")  # noqa: TRY301

                if validate_status == "connection_error":
                    raise ValueError("Connection error.")  # noqa: TRY301
                
                # Check if 'devices' is an empty list and 'deviceTypes' has a single data
                if isinstance(selected_device.get("devices"), list) and not selected_device["devices"]:
                    if isinstance(selected_device.get("deviceTypes"), list) and len(selected_device["deviceTypes"]) == 1:
                        # Set 'devices' to be the same as 'deviceTypes'
                        selected_device["devices"] = selected_device["deviceTypes"]

                return self.async_create_entry(
                    title=selected_device["name"],
                    data={
                        CONF_DEVICE: selected_device,
                        CONF_HOST: user_input[CONF_HOST],
                        CONF_MQTT_PASS: selected_device["mqttPassword"],
                        CONF_DEVICE_ID: selected_device["uuidRef"]["uuid"],
                        CONF_API_KEY: self.api_token,
                    },
                )

            except Exception as e:  # noqa: BLE001
                _LOGGER.error("Device selection error: %s", e)
                errors["base"] = str(e)

        # Show device selection form with IP configuration
        device_schema = vol.Schema(
            {
                vol.Required(CONF_DEVICE_ID): vol.In(device_options),
                vol.Required(CONF_HOST): str,
            }
        )

        return self.async_show_form(
            step_id="select_device", data_schema=device_schema, errors=errors
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class TinxyLocalOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Tinxy Local options to change API token."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage the options to update API token."""
        if user_input is not None:
            # Validate the new token if provided
            try:
                await validate_input(self.hass, user_input)
                # Update entry with the new API key
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data={
                        **self.config_entry.data,
                        CONF_API_KEY: user_input[CONF_API_KEY],
                    },
                )
                return self.async_create_entry(title="", data={})
            except InvalidAuth:
                return self.async_show_form(
                    step_id="init",
                    data_schema=STEP_USER_DATA_SCHEMA,
                    errors={"base": "invalid_auth"},
                )
            except CannotConnect:
                return self.async_show_form(
                    step_id="init",
                    data_schema=STEP_USER_DATA_SCHEMA,
                    errors={"base": "cannot_connect"},
                )
            except Exception:
                _LOGGER.exception("Unexpected exception during token update")
                return self.async_show_form(
                    step_id="init",
                    data_schema=STEP_USER_DATA_SCHEMA,
                    errors={"base": "unknown"},
                )

        # Show form for updating API token
        return self.async_show_form(step_id="init", data_schema=STEP_USER_DATA_SCHEMA)
