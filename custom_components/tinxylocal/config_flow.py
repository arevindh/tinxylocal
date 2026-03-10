"""Config flow for Tinxy Local integration."""

from __future__ import annotations

import logging
import socket
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.zeroconf import async_get_async_instance
from homeassistant.const import CONF_API_KEY, CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import selector
from zeroconf.asyncio import AsyncServiceInfo

from .const import CONF_DEVICE, CONF_DEVICE_ID, CONF_MQTT_PASS, CONF_POLLING_INTERVAL, CONF_REQUEST_TIMEOUT, DEFAULT_POLLING_INTERVAL, DEFAULT_REQUEST_TIMEOUT, DOMAIN, TINXY_BACKEND
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
    hub = TinxyLocalHub(hass, host_ip)
    return hub.validate_ip(web_session, host_ip, chip_id)


async def read_devices(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Read Device List."""
    web_session = async_get_clientsession(hass)
    _LOGGER.debug("Fetching device list for configured account")

    host_config = TinxyHostConfiguration(
        api_token=data[CONF_API_KEY], api_url=TINXY_BACKEND
    )
    api = TinxyCloud(host_config=host_config, web_session=web_session)

    return await api.get_device_list()


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the API key and fetch device list."""
    web_session = async_get_clientsession(hass)
    hub = TinxyLocalHub(hass, TINXY_BACKEND)

    if not await hub.authenticate(data[CONF_API_KEY], web_session):
        raise InvalidAuth

    return {"title": "Tinxy.in"}


def find_device_by_id(devicelist, target_id):
    """Find device by its ID in the list."""
    for device in devicelist:
        if device["_id"] == target_id:
            return device
    return None


async def discover_device_host(hass: HomeAssistant, device_id: str) -> tuple[str, str]:
    """Resolve a Tinxy device's local host, returning (host, method).

    Tries mDNS first to get the actual IP address. If that fails, falls back
    to the guaranteed .local mDNS hostname (tinxy{last5}.local) which works
    on any network with mDNS — no static IP required.

    Returns:
        (host, method) where method is 'ip', 'hostname', or 'fallback'.
    """
    suffix = device_id[-5:]
    local_hostname = f"tinxy{suffix}.local"
    service_name = f"tinxy{suffix}._http._tcp.local."
    _LOGGER.debug("Searching for mDNS service: %s", service_name)
    try:
        zc = await async_get_async_instance(hass)
        info = AsyncServiceInfo("_http._tcp.local.", service_name)
        if await info.async_request(zc, 3000):
            if info.addresses:
                ip = socket.inet_ntoa(info.addresses[0])
                _LOGGER.debug("Auto-discovered %s at %s (IP)", device_id, ip)
                return ip, "ip"
            # Service found but no IP — use the server name from the record
            if info.server:
                hostname = info.server.rstrip(".")
                _LOGGER.debug("Auto-discovered %s as %s (hostname)", device_id, hostname)
                return hostname, "hostname"
        _LOGGER.debug("mDNS lookup timed out, using .local hostname fallback")
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("mDNS discovery failed for device %s: %s", device_id, err)
    return local_hostname, "fallback"


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tinxy Local."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self.api_token = None
        self.cloud_devices = {}
        self._selected_device: dict[str, Any] | None = None
        self._discovered_host: str | None = None
        self._discovery_method: str = "manual"

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> TinxyLocalOptionsFlowHandler:
        """Get the options flow for this handler.
        """
        return TinxyLocalOptionsFlowHandler()

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
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 1: Choose a device from the cloud device list."""
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
            selected_device = find_device_by_id(
                self.cloud_devices, user_input[CONF_DEVICE_ID]
            )
            if not selected_device:
                return self.async_show_form(
                    step_id="select_device",
                    data_schema=vol.Schema({vol.Required(CONF_DEVICE_ID): vol.In(device_options)}),
                    errors={"base": "device_not_found"},
                )

            self._selected_device = selected_device

            # Attempt mDNS auto-discovery before showing the IP form
            self._discovered_host, self._discovery_method = await discover_device_host(
                self.hass, selected_device["_id"]
            )
            _LOGGER.info(
                "Host for %s: %s (method: %s)",
                selected_device["name"],
                self._discovered_host,
                self._discovery_method,
            )

            return await self.async_step_configure_ip()

        return self.async_show_form(
            step_id="select_device",
            data_schema=vol.Schema({vol.Required(CONF_DEVICE_ID): vol.In(device_options)}),
        )

    async def async_step_configure_ip(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 2: Confirm or enter the device IP (pre-filled from mDNS if found)."""
        errors: dict[str, str] = {}
        selected_device = self._selected_device

        if user_input:
            try:
                web_session = async_get_clientsession(self.hass)
                hub = TinxyLocalHub(self.hass, user_input[CONF_HOST])
                validate_status = await hub.validate_ip(
                    web_session,
                    selected_device["uuidRef"]["uuid"],
                )

                _LOGGER.debug("IP validation status: %s", validate_status)

                if validate_status == "wrong_chip_id":
                    raise ValueError(  # noqa: TRY301
                        "Wrong IP address — expected chip ID {}".format(
                            selected_device["uuidRef"]["uuid"]
                        )
                    )
                if validate_status == "api_not_available":
                    raise ValueError("Local API not available.")  # noqa: TRY301
                if validate_status == "connection_error":
                    raise ValueError("Connection error.")  # noqa: TRY301

                # Normalise empty-device edge case
                if isinstance(selected_device.get("devices"), list) and not selected_device["devices"]:
                    if isinstance(selected_device.get("deviceTypes"), list) and len(selected_device["deviceTypes"]) == 1:
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
                _LOGGER.error("IP configuration error: %s", e)
                errors["base"] = str(e)

        # Build IP schema — pre-fill with discovered host if available
        ip_schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=self._discovered_host or vol.UNDEFINED): str,
            }
        )

        _method_labels = {
            "ip": "✓ Resolved IP address via mDNS: {host}",
            "hostname": "✓ Found mDNS hostname: {host}",
            "fallback": "Using .local hostname: {host} (no static IP needed)",
            "manual": "Enter the device IP address or hostname manually.",
        }
        status_template = _method_labels.get(self._discovery_method, _method_labels["manual"])
        discovery_status = status_template.format(host=self._discovered_host or "")

        description_placeholders = {
            "device_name": selected_device["name"],
            "discovery_status": discovery_status,
        }

        return self.async_show_form(
            step_id="configure_ip",
            data_schema=ip_schema,
            description_placeholders=description_placeholders,
            errors=errors,
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class TinxyLocalOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Tinxy Local options to change API token."""

    def __init__(self) -> None:
        """Initialize options flow."""
        return None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage the options to update API token and request timeout."""
        errors: dict[str, str] = {}
        
        if user_input is not None:
            # Validate polling interval vs timeout
            timeout = user_input.get(CONF_REQUEST_TIMEOUT, self.config_entry.options.get(CONF_REQUEST_TIMEOUT, DEFAULT_REQUEST_TIMEOUT))
            polling = user_input.get(CONF_POLLING_INTERVAL, self.config_entry.options.get(CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL))
            
            if polling < timeout:
                errors["polling_interval"] = "polling_less_than_timeout"
                return self.async_show_form(
                    step_id="init",
                    data_schema=self._get_options_schema(),
                    errors=errors,
                )
            
            # Update entry with the new settings
            updated_data = {**self.config_entry.data}
            updated_options = {**self.config_entry.options}  # Preserve existing options
            
            # Update host IP if changed
            if CONF_HOST in user_input and user_input[CONF_HOST] != self.config_entry.data.get(CONF_HOST):
                updated_data[CONF_HOST] = user_input[CONF_HOST]
            
            # Update API key if changed
            if CONF_API_KEY in user_input and user_input[CONF_API_KEY] != self.config_entry.data.get(CONF_API_KEY):
                try:
                    await validate_input(self.hass, user_input)
                    updated_data[CONF_API_KEY] = user_input[CONF_API_KEY]
                except InvalidAuth:
                    return self.async_show_form(
                        step_id="init",
                        data_schema=self._get_options_schema(),
                        errors={"base": "invalid_auth"},
                    )
                except CannotConnect:
                    return self.async_show_form(
                        step_id="init",
                        data_schema=self._get_options_schema(),
                        errors={"base": "cannot_connect"},
                    )
                except Exception:
                    _LOGGER.exception("Unexpected exception during token update")
                    return self.async_show_form(
                        step_id="init",
                        data_schema=self._get_options_schema(),
                        errors={"base": "unknown"},
                    )
            
            # Update request timeout
            updated_options[CONF_REQUEST_TIMEOUT] = timeout
            
            # Update polling interval
            updated_options[CONF_POLLING_INTERVAL] = polling
            
            # Update the config entry
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data=updated_data,
                options=updated_options,
            )
            
            # Schedule reload in background so form closes properly first
            self.hass.async_create_task(
                self.hass.config_entries.async_reload(self.config_entry.entry_id)
            )
            
            return self.async_create_entry(title="", data=updated_options)

        # Show form for updating settings
        return self.async_show_form(
            step_id="init", 
            data_schema=self._get_options_schema()
        )
    
    def _get_options_schema(self) -> vol.Schema:
        """Get the options schema with current values as defaults."""
        # Get fresh config entry to avoid stale data
        fresh_entry = self.hass.config_entries.async_get_entry(self.config_entry.entry_id)
        options = fresh_entry.options if fresh_entry else self.config_entry.options
        
        current_timeout = options.get(
            CONF_REQUEST_TIMEOUT,
            DEFAULT_REQUEST_TIMEOUT
        )
        current_polling = options.get(
            CONF_POLLING_INTERVAL,
            DEFAULT_POLLING_INTERVAL
        )
        current_api_key = self.config_entry.data.get(CONF_API_KEY, "")
        current_host = self.config_entry.data.get(CONF_HOST, "")
        
        return vol.Schema(
            {
                vol.Optional(CONF_HOST, default=current_host): str,
                vol.Optional(CONF_API_KEY, default=current_api_key): selector.TextSelector(
                    selector.TextSelectorConfig(
                        type=selector.TextSelectorType.PASSWORD,
                        autocomplete="off",
                    )
                ),
                vol.Optional(
                    CONF_REQUEST_TIMEOUT, 
                    default=current_timeout
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1,
                        max=60,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="seconds",
                    )
                ),
                vol.Optional(
                    CONF_POLLING_INTERVAL,
                    default=current_polling
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=3,
                        max=600,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="seconds",
                    )
                ),
            }
        )
