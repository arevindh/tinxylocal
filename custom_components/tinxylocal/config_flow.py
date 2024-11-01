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

from .const import (
    CONF_ADD_DEVICE,
    CONF_DEVICE,
    CONF_DEVICE_ID,
    CONF_EDIT_DEVICE,
    CONF_MQTT_PASS,
    CONF_SETUP_CLOUD,
    DOMAIN,
    TINXY_BACKEND,
)
from .hub import TinxyLocalHub
from .tinxycloud import TinxyCloud, TinxyHostConfiguration

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_KEY): str,
    }
)

STEP_DEVICE_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_MQTT_PASS): str,
        vol.Required(CONF_DEVICE_ID): str,
    }
)

CONF_ACTIONS = {
    CONF_ADD_DEVICE: "Add a new device",
    CONF_EDIT_DEVICE: "Edit a device",
    CONF_SETUP_CLOUD: "Reconfigure Cloud API account",
}


async def read_devices(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Read Device List."""
    web_session = async_get_clientsession(hass)
    _LOGGER.info(data)

    host_config = TinxyHostConfiguration(
        api_token=data[CONF_API_KEY], api_url=TINXY_BACKEND
    )
    api = TinxyCloud(host_config=host_config, web_session=web_session)

    return await api.get_device_list()


async def toggle_device(
    hass: HomeAssistant, host: str, mqttpass: str, relay_number: int, action: int
) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    web_session = async_get_clientsession(hass)
    hub = TinxyLocalHub(host)

    data = await hub.tinxy_toggle(
        mqttpass=mqttpass,
        relay_number=relay_number,
        action=action,
        web_session=web_session,
    )

    return data


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    web_session = async_get_clientsession(hass)
    hub = TinxyLocalHub(TINXY_BACKEND)

    if not await hub.authenticate(data[CONF_API_KEY], web_session):
        raise InvalidAuth

    return {"title": "Tinxy.in"}


def find_device_by_id(devicelist, target_id):
    """Find."""
    for device in devicelist:
        if device["_id"] == target_id:
            return device
    return None


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tinxy Local."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize local tinxy options flow."""
        # self.config_entry = config_entry
        self.selected_device = None
        self.mqtt_pass = None
        self.cloud_devices = {}
        self.host = None
        self.api_token = None
        self.device_uuid = None

        self.discovered_devices = {}
        self.editing_device = False

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        # After Picking device
        if user_input is not None and CONF_DEVICE_ID in user_input:
            try:
                _LOGGER.error(user_input[CONF_DEVICE_ID])

                device = None

                device = find_device_by_id(
                    self.cloud_devices, user_input[CONF_DEVICE_ID]
                )

                # _LOGGER.error(device, exc_info=device)

                self.mqtt_pass = device["mqttPassword"]
                self.device_uuid = device["uuidRef"]["uuid"]
                self.host = user_input[CONF_HOST]

                _LOGGER.error(
                    {self.mqtt_pass, self.device_uuid, self.host}, exc_info=device
                )
                _LOGGER.error(device, exc_info=device)

                data = await toggle_device(self.hass, self.host, self.mqtt_pass, 1, 0)

                _LOGGER.error(data)

                return self.async_create_entry(
                    title=device["name"],
                    data={
                        CONF_DEVICE: device,
                        CONF_HOST: self.host,
                        CONF_MQTT_PASS: self.mqtt_pass,
                        CONF_DEVICE_ID: self.device_uuid,
                        CONF_API_KEY: self.api_token,
                    },
                )
                # await validate_input(self.hass, self.api_token)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        # After submitting api key
        elif user_input is not None and CONF_API_KEY in user_input:
            try:
                await validate_input(self.hass, user_input)

                # Save after validated
                self.api_token = user_input[CONF_API_KEY]

                self.cloud_devices = await read_devices(self.hass, user_input)

                device_schema_data = {
                    item["_id"]: "{} ({})".format(item["name"], item["uuidRef"]["uuid"])
                    for item in self.cloud_devices
                    if "mqttPassword" in item
                    and "uuidRef" in item
                    and "uuid" in item["uuidRef"]
                }

                device_schema = vol.Schema(
                    {
                        vol.Required("device_id", default=None): vol.In(
                            device_schema_data
                        ),
                        vol.Required(CONF_HOST): str,
                    }
                )

                return self.async_show_form(
                    step_id="user",
                    data_schema=device_schema,
                    description_placeholders=self.cloud_devices,
                    errors=errors,
                )

            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
