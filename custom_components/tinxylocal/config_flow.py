"""Config flow for Tinxy Local integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY, CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import selector
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .const import CONF_DEVICE, CONF_DEVICE_ID, CONF_MQTT_PASS, CONF_POLLING_INTERVAL, CONF_RATE_LIMIT_DELAY, CONF_REQUEST_TIMEOUT, DEFAULT_POLLING_INTERVAL, DEFAULT_RATE_LIMIT_DELAY, DEFAULT_REQUEST_TIMEOUT, DOMAIN, TINXY_BACKEND
from .hub import TinxyConnectionException, TinxyLocalHub
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


async def read_devices(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Read Device List."""
    web_session = async_get_clientsession(hass)

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


def _backfill_device_names(device: dict[str, Any]) -> None:
    """Give single-relay devices (locks etc.) a name list, which the cloud leaves empty."""
    if isinstance(device.get("devices"), list) and not device["devices"]:
        if isinstance(device.get("deviceTypes"), list) and len(device["deviceTypes"]) == 1:
            device["devices"] = device["deviceTypes"]


def _entry_data(device: dict[str, Any], host: str, api_token: str) -> dict[str, Any]:
    """Build the config entry payload for a selected cloud device."""
    _backfill_device_names(device)
    return {
        CONF_DEVICE: device,
        CONF_HOST: host,
        CONF_MQTT_PASS: device["mqttPassword"],
        CONF_DEVICE_ID: device["uuidRef"]["uuid"],
        CONF_API_KEY: api_token,
    }


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
        self.discovered_host: str | None = None
        self.discovered_chip_id: str | None = None

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> TinxyLocalOptionsFlowHandler:
        """Get the options flow for this handler.
        """
        return TinxyLocalOptionsFlowHandler()

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> config_entries.ConfigFlowResult:
        """Handle a Tinxy device announcing itself over mDNS."""
        host = str(discovery_info.ip_address)

        # The mDNS name only carries a truncated id, so ask the device itself.
        try:
            info = await TinxyLocalHub(self.hass, host).get_info(
                async_get_clientsession(self.hass)
            )
        except TinxyConnectionException:
            return self.async_abort(reason="cannot_connect")

        if not info or not info.get("chip_id"):
            return self.async_abort(reason="api_not_available")

        # Same unique id the manual path uses, so a device added either way is
        # recognised by the other. `updates` re-points an existing entry at the
        # new address when DHCP moves the device.
        await self.async_set_unique_id(str(info["chip_id"]).strip())
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})

        self.discovered_host = host
        self.discovered_chip_id = str(info["chip_id"]).strip()
        self.context["title_placeholders"] = {"name": f"Tinxy ({host})"}

        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Match a discovered device against the user's cloud account and add it."""
        errors: dict[str, str] = {}

        # Reuse a token from an already-configured device so this is one click.
        if self.api_token is None:
            for entry in self._async_current_entries():
                if CONF_API_KEY in entry.data:
                    self.api_token = entry.data[CONF_API_KEY]
                    break

        if user_input is not None:
            self.api_token = user_input.get(CONF_API_KEY) or self.api_token
            try:
                devices = await read_devices(self.hass, {CONF_API_KEY: self.api_token})
                device = next(
                    (
                        item
                        for item in devices
                        if item.get("uuidRef", {}).get("uuid")
                        == self.discovered_chip_id
                        and "mqttPassword" in item
                    ),
                    None,
                )
                if device is None:
                    errors["base"] = "device_not_in_account"
                else:
                    return self.async_create_entry(
                        title=device["name"],
                        data=_entry_data(device, self.discovered_host, self.api_token),
                    )
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Failed to look up discovered device")
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="zeroconf_confirm",
            data_schema=vol.Schema(
                {vol.Required(CONF_API_KEY, default=self.api_token or ""): str}
            ),
            errors=errors,
            description_placeholders={
                "host": self.discovered_host or "",
                "chip_id": self.discovered_chip_id or "",
            },
        )

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

        # A choose_token submission is routed to async_step_choose_token by
        # Home Assistant, so it never comes back through this step.

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

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Re-point an entry at a new address, or replace its API token.

        The chip id is checked exactly as initial setup checks it, so a typo
        cannot silently attach an entry to a different physical device. This is
        where host and token are edited; options carries only the timings.
        """
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                if user_input[CONF_API_KEY] != entry.data.get(CONF_API_KEY):
                    await validate_input(self.hass, user_input)

                hub = TinxyLocalHub(self.hass, user_input[CONF_HOST])
                status = await hub.validate_ip(
                    async_get_clientsession(self.hass),
                    entry.data[CONF_DEVICE]["uuidRef"]["uuid"],
                )
                if status != "ok":
                    errors["base"] = {
                        "wrong_chip_id": "wrong_chip_id",
                        "api_not_available": "api_not_available",
                    }.get(status, "cannot_connect")
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error while reconfiguring")
                errors["base"] = "unknown"

            if not errors:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_HOST: user_input[CONF_HOST],
                        CONF_API_KEY: user_input[CONF_API_KEY],
                    },
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=entry.data[CONF_HOST]): str,
                    vol.Required(
                        CONF_API_KEY, default=entry.data.get(CONF_API_KEY, "")
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD,
                            autocomplete="off",
                        )
                    ),
                }
            ),
            errors=errors,
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
                hub = TinxyLocalHub(self.hass, user_input[CONF_HOST])
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

                # Keyed on the chip id so mDNS discovery recognises this device later.
                await self.async_set_unique_id(selected_device["uuidRef"]["uuid"])
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=selected_device["name"],
                    data=_entry_data(
                        selected_device, user_input[CONF_HOST], self.api_token
                    ),
                )

            except AbortFlow:
                # "already configured" must abort the flow, not land in the form.
                raise
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
    """Handle Tinxy Local timing options."""

    def __init__(self) -> None:
        """Initialize options flow."""
        return None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage the timing options. Host and token live in the reconfigure flow."""
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
            
            updated_options = {**self.config_entry.options}  # Preserve existing options

            # Update request timeout
            updated_options[CONF_REQUEST_TIMEOUT] = timeout
            
            # Update polling interval
            updated_options[CONF_POLLING_INTERVAL] = polling

            # Update command spacing
            updated_options[CONF_RATE_LIMIT_DELAY] = user_input.get(
                CONF_RATE_LIMIT_DELAY,
                self.config_entry.options.get(
                    CONF_RATE_LIMIT_DELAY, DEFAULT_RATE_LIMIT_DELAY
                ),
            )
            
            # Update the config entry
            self.hass.config_entries.async_update_entry(
                self.config_entry,
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
        current_rate_limit = options.get(
            CONF_RATE_LIMIT_DELAY,
            DEFAULT_RATE_LIMIT_DELAY
        )
        return vol.Schema(
            {
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
                vol.Optional(
                    CONF_RATE_LIMIT_DELAY,
                    default=current_rate_limit
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1,
                        max=10,
                        step=0.5,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="seconds",
                    )
                ),
            }
        )
