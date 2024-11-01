"""Module for interacting with Tinxy devices locally."""

from datetime import timedelta
import logging

from homeassistant.util import Throttle
from homeassistant.helpers.debounce import Debouncer
from homeassistant.core import HomeAssistant
import asyncio

from .const import TINXY_BACKEND

# pylint: disable=no-name-in-module
from .encrypt import PasswordEncryptor
from .tinxycloud import TinxyCloud, TinxyHostConfiguration

_LOGGER = logging.getLogger(__name__)


class TinxyConnectionException(Exception):
    """Exception for connection errors with Tinxy devices."""


class TinxyLocalException(Exception):
    """General exception for Tinxy local device errors."""


class TinxyLocalHub:
    """TinxyLocalHub class for interacting with Tinxy devices locally."""

    def __init__(self, host: str) -> None:
        """Initialize with the device host."""
        self.host = f"http://{host}"

    async def authenticate(self, api_key: str, web_session) -> bool:
        """Test if we can authenticate with the host."""
        host_config = TinxyHostConfiguration(api_token=api_key, api_url=TINXY_BACKEND)
        api = TinxyCloud(host_config=host_config, web_session=web_session)
        await api.sync_devices()
        return True

    async def _request(
        self, method: str, endpoint: str, payload: dict = None, web_session=None
    ) -> dict:
        """Inner function to handle HTTP requests and error checking."""
        url = f"{self.host}{endpoint}"
        headers = {"Content-Type": "application/json"}

        # Choose between POST or GET request based on the method
        async with web_session.request(
            method, url=url, json=payload if method == "POST" else None, headers=headers
        ) as resp:
            if resp.status == 200:
                return await resp.json(content_type=None)
            if resp.status == 400:
                _LOGGER.error(
                    "Failed to process request at %s: HTTP status %s", url, resp.status
                )
                raise TinxyConnectionException(
                    f"Failed to process request: HTTP status {resp.status}"
                )
            return None

    @Throttle(timedelta(seconds=1))
    async def tinxy_toggle(
        self, mqttpass: str, relay_number: int, action: int, web_session
    ) -> bool:
        """Toggle Tinxy device state."""
        password = PasswordEncryptor(mqttpass).generate_password()
        if action not in [0, 1]:
            _LOGGER.error("Action must be 0 (off) or 1 (on): %s", action)
            return False

        payload = {
            "password": password,
            "relayNumber": relay_number,
            "action": str(action),
        }
        try:
            # Use the _request function for POST toggle action
            return await self._request("POST", "/toggle", payload, web_session)
        except TinxyConnectionException as e:
            _LOGGER.error("Error toggling device relay %s: %s", relay_number, e)
            return False

    async def fetch_device_data(self, node, web_session):
        """Fetch data from the device and update the device status."""
        try:
            # Use the _request function for GET data retrieval
            device_data = await self._request("GET", "/info", web_session=web_session)
            return self.decode_device_data(device_data, node)
        except TinxyConnectionException as e:
            _LOGGER.error("Failed to update status for node %s: %s", node["name"], e)
            raise TinxyLocalException("Error fetching device data") from e

    def decode_device_data(self, data, node):
        """Decode the device data."""
        decoded_data = {
            "rssi": data["rssi"],
            "ip": data["ip"],
            "version": data["version"],
            "status": data["status"],
            "chip_id": data["chip_id"],
            "ssid": data["ssid"],
            "firmware": data["firmware"],
            "model": data["model"],
            "devices": [],
        }

        state_array = [
            {
                "name": node["devices"][index]["name"],
                "type": node["devices"][index]["type"],
                "status": "on" if status == "1" else "off",
            }
            for index, status in enumerate(data["state"])
        ]

        if "bright" in data:
            brightness_array = [
                data["bright"][i : i + 3] for i in range(0, len(data["bright"]), 3)
            ]
            for index, device in enumerate(state_array):
                if device["type"] in ["light", "fan"]:
                    brightness_value = int(brightness_array[index] or "000", 10)
                    device["brightness"] = brightness_value

        decoded_data["devices"] = state_array
        return decoded_data
