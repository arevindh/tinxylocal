"""Config flow tests. Bronze `config-flow-test-coverage` wants all paths."""

from ipaddress import ip_address
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY, CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from custom_components.tinxylocal.const import (
    CONF_DEVICE_ID,
    CONF_POLLING_INTERVAL,
    CONF_RATE_LIMIT_DELAY,
    CONF_REQUEST_TIMEOUT,
    DOMAIN,
)

from .const import (
    API_KEY,
    CHIP_ID,
    CLOUD_DEVICES,
    CLOUD_URL,
    DEVICE_ID,
    DEVICE_INFO,
    ENTRY_DATA,
    HOST,
    INFO_URL,
    MQTT_PASS,
)

DISCOVERY = ZeroconfServiceInfo(
    ip_address=ip_address(HOST),
    ip_addresses=[ip_address(HOST)],
    hostname="tinxy3de52.local.",
    name="tinxy3de52._http._tcp.local.",
    port=80,
    type="_http._tcp.local.",
    properties={},
)


# --------------------------------------------------------------- manual flow


async def test_user_flow_creates_entry(
    hass: HomeAssistant, device_online: AiohttpClientMocker
) -> None:
    """Token, then device plus IP, produces an entry keyed on the chip id."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: API_KEY}
    )
    assert result["step_id"] == "select_device"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_DEVICE_ID: DEVICE_ID, CONF_HOST: HOST}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Hall"
    assert result["data"][CONF_HOST] == HOST
    assert result["data"]["mqtt_pass"] == MQTT_PASS
    # unique_id is the chip id, so discovery recognises this device later
    assert result["result"].unique_id == CHIP_ID


async def test_user_flow_unknown_error(hass: HomeAssistant) -> None:
    """An unexpected failure while validating shows an error, not a crash."""
    with patch(
        "custom_components.tinxylocal.config_flow.validate_input",
        side_effect=RuntimeError("boom"),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: API_KEY}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}


async def test_user_flow_invalid_auth(hass: HomeAssistant) -> None:
    """A rejected token is reported as invalid auth."""
    from custom_components.tinxylocal.config_flow import InvalidAuth

    with patch(
        "custom_components.tinxylocal.config_flow.validate_input",
        side_effect=InvalidAuth,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: API_KEY}
        )
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_cannot_connect(hass: HomeAssistant) -> None:
    """A cloud outage is reported as cannot connect."""
    from custom_components.tinxylocal.config_flow import CannotConnect

    with patch(
        "custom_components.tinxylocal.config_flow.validate_input",
        side_effect=CannotConnect,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: API_KEY}
        )
    assert result["errors"] == {"base": "cannot_connect"}


@pytest.mark.parametrize(
    ("status", "fragment"),
    [
        ("wrong_chip_id", "chip id"),
        ("api_not_available", "Local API not available"),
        ("connection_error", "Connection error"),
    ],
)
async def test_select_device_rejects_bad_ip(
    hass: HomeAssistant, device_online: AiohttpClientMocker, status: str, fragment: str
) -> None:
    """A wrong or unreachable IP must not silently attach to another device."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: API_KEY}
    )
    with patch(
        "custom_components.tinxylocal.hub.TinxyLocalHub.validate_ip",
        return_value=status,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_DEVICE_ID: DEVICE_ID, CONF_HOST: HOST}
        )
    assert result["type"] is FlowResultType.FORM
    assert fragment.lower() in result["errors"]["base"].lower()


async def test_select_device_unknown_device(
    hass: HomeAssistant, device_online: AiohttpClientMocker
) -> None:
    """An id absent from the account is rejected.

    The step is driven directly because the form schema is `vol.In(...)`, which
    rejects an unknown id before the step body runs. The guard inside the step
    is the defence for a stale cached device list.
    """
    from custom_components.tinxylocal.config_flow import ConfigFlow

    flow = ConfigFlow()
    flow.hass = hass
    flow.api_token = API_KEY

    result = await flow.async_step_select_device(
        {CONF_DEVICE_ID: "does-not-exist", CONF_HOST: HOST}
    )
    assert result["type"] is FlowResultType.FORM
    assert "not found" in result["errors"]["base"].lower()


async def test_select_device_already_configured_aborts(
    hass: HomeAssistant, device_online: AiohttpClientMocker, mock_entry: MockConfigEntry
) -> None:
    """Adding the same device twice aborts instead of landing in the form.

    `_abort_if_unique_id_configured` raises AbortFlow, which the step's broad
    except would otherwise convert into a form error.
    """
    mock_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"token_choice": "existing"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_DEVICE_ID: DEVICE_ID, CONF_HOST: HOST}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_existing_token_is_offered(
    hass: HomeAssistant, device_online: AiohttpClientMocker, mock_entry: MockConfigEntry
) -> None:
    """With a device already set up, the flow offers the saved token."""
    mock_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["step_id"] == "choose_token"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"token_choice": "new"}
    )
    assert result["step_id"] == "user"


# ------------------------------------------------------------ zeroconf flow


async def test_zeroconf_discovery_creates_entry(
    hass: HomeAssistant, device_online: AiohttpClientMocker
) -> None:
    """A discovered device is matched to the account by chip id."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=DISCOVERY
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "zeroconf_confirm"
    assert result["description_placeholders"]["host"] == HOST
    assert result["description_placeholders"]["chip_id"] == CHIP_ID

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: API_KEY}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Hall"
    assert result["result"].unique_id == CHIP_ID


async def test_zeroconf_unreachable_aborts(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A device that does not answer /info is not offered."""
    aioclient_mock.get(INFO_URL, status=500)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=DISCOVERY
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


async def test_zeroconf_without_chip_id_aborts(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Something answering /info without a chip id is not a usable Tinxy."""
    aioclient_mock.get(INFO_URL, json={"model": "something else"})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=DISCOVERY
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "api_not_available"


async def test_zeroconf_existing_device_updates_host(
    hass: HomeAssistant, device_online: AiohttpClientMocker, mock_entry: MockConfigEntry
) -> None:
    """DHCP moved the device: adopt the new address, do not duplicate it."""
    mock_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_entry, data={**ENTRY_DATA, CONF_HOST: "10.0.28.99"}
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=DISCOVERY
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert mock_entry.data[CONF_HOST] == HOST


async def test_zeroconf_device_not_in_account(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A Tinxy belonging to a different account is reported clearly."""
    aioclient_mock.get(INFO_URL, json={**DEVICE_INFO, "chip_id": "99999999"})
    aioclient_mock.get(CLOUD_URL, json=CLOUD_DEVICES)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=DISCOVERY
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: API_KEY}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "device_not_in_account"}


async def test_zeroconf_cloud_failure(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A cloud lookup failure during discovery is reported, not raised."""
    aioclient_mock.get(INFO_URL, json=DEVICE_INFO)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=DISCOVERY
    )
    with patch(
        "custom_components.tinxylocal.config_flow.read_devices",
        side_effect=RuntimeError("cloud down"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: API_KEY}
        )
    assert result["errors"] == {"base": "cannot_connect"}


# ----------------------------------------------------------- options flow


async def test_options_flow_saves_settings(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """Timeout, polling and command spacing round-trip into options."""
    result = await hass.config_entries.options.async_init(loaded_entry.entry_id)
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_HOST: HOST,
            CONF_API_KEY: API_KEY,
            CONF_REQUEST_TIMEOUT: 8,
            CONF_POLLING_INTERVAL: 15,
            CONF_RATE_LIMIT_DELAY: 2,
        },
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert loaded_entry.options[CONF_REQUEST_TIMEOUT] == 8
    assert loaded_entry.options[CONF_POLLING_INTERVAL] == 15
    assert loaded_entry.options[CONF_RATE_LIMIT_DELAY] == 2


async def test_options_flow_rejects_polling_below_timeout(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """Polling faster than the timeout would overlap requests."""
    result = await hass.config_entries.options.async_init(loaded_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_HOST: HOST,
            CONF_API_KEY: API_KEY,
            CONF_REQUEST_TIMEOUT: 10,
            CONF_POLLING_INTERVAL: 5,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"polling_interval": "polling_less_than_timeout"}


async def test_options_flow_rejects_bad_new_token(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """A replacement token is validated before it is stored."""
    from custom_components.tinxylocal.config_flow import InvalidAuth

    result = await hass.config_entries.options.async_init(loaded_entry.entry_id)
    with patch(
        "custom_components.tinxylocal.config_flow.validate_input",
        side_effect=InvalidAuth,
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                CONF_HOST: HOST,
                CONF_API_KEY: "a-different-token",
                CONF_REQUEST_TIMEOUT: 5,
                CONF_POLLING_INTERVAL: 6,
            },
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert loaded_entry.data[CONF_API_KEY] == API_KEY


async def test_lock_gets_a_relay_name_backfilled(
    hass: HomeAssistant, device_online: AiohttpClientMocker
) -> None:
    """Locks come back from the cloud with an empty `devices` list."""
    with patch(
        "custom_components.tinxylocal.hub.TinxyLocalHub.validate_ip", return_value="ok"
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: API_KEY}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_DEVICE_ID: "60a1b2c3d4e5f60718293a4b", CONF_HOST: HOST},
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    # backfilled from deviceTypes so the lock platform has something to name
    assert result["data"]["device"]["devices"] == ["Lock"]


async def test_rejected_token_raises_invalid_auth(hass: HomeAssistant) -> None:
    """validate_input turns a falsy authenticate into InvalidAuth."""
    from custom_components.tinxylocal.config_flow import InvalidAuth, validate_input

    with (
        patch(
            "custom_components.tinxylocal.hub.TinxyLocalHub.authenticate",
            return_value=False,
        ),
        pytest.raises(InvalidAuth),
    ):
        await validate_input(hass, {CONF_API_KEY: API_KEY})


async def test_zeroconf_reuses_a_saved_token(
    hass: HomeAssistant, device_online: AiohttpClientMocker, mock_entry: MockConfigEntry
) -> None:
    """A second device is one click: the token comes from the first entry."""
    mock_entry.add_to_hass(hass)
    device_online.clear_requests()
    device_online.get(
        "http://10.0.28.17/info", json={**DEVICE_INFO, "chip_id": "5610150"}
    )
    device_online.get(CLOUD_URL, json=CLOUD_DEVICES)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=DISCOVERY
    )
    assert result["step_id"] == "zeroconf_confirm"
    # the saved token is pre-filled, so submitting the form as-is works
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: API_KEY}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Front Door"


async def test_options_flow_updates_host(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """A device moved by hand can be re-pointed without re-adding it."""
    result = await hass.config_entries.options.async_init(loaded_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_HOST: "10.0.28.55",
            CONF_API_KEY: API_KEY,
            CONF_REQUEST_TIMEOUT: 5,
            CONF_POLLING_INTERVAL: 6,
        },
    )
    await hass.async_block_till_done()
    assert loaded_entry.data[CONF_HOST] == "10.0.28.55"


@pytest.mark.parametrize(
    ("error", "expected"),
    [("CannotConnect", "cannot_connect"), ("RuntimeError", "unknown")],
)
async def test_options_flow_token_update_failures(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, error: str, expected: str
) -> None:
    """A new token that cannot be checked leaves the stored one alone."""
    import custom_components.tinxylocal.config_flow as cf

    exc = getattr(cf, error, None) or RuntimeError
    result = await hass.config_entries.options.async_init(loaded_entry.entry_id)
    with patch.object(cf, "validate_input", side_effect=exc):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                CONF_HOST: HOST,
                CONF_API_KEY: "replacement-token",
                CONF_REQUEST_TIMEOUT: 5,
                CONF_POLLING_INTERVAL: 6,
            },
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}
    assert loaded_entry.data[CONF_API_KEY] == API_KEY


async def test_options_flow_accepts_a_new_token(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, device_online: AiohttpClientMocker
) -> None:
    """A replacement token that validates is stored."""
    result = await hass.config_entries.options.async_init(loaded_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_HOST: HOST,
            CONF_API_KEY: "a-fresh-token",
            CONF_REQUEST_TIMEOUT: 5,
            CONF_POLLING_INTERVAL: 6,
        },
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert loaded_entry.data[CONF_API_KEY] == "a-fresh-token"
