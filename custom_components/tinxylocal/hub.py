"""Module for interacting with Tinxy devices locally."""

from datetime import timedelta
import logging

import aiohttp

from homeassistant.util import Throttle

from .const import TINXY_BACKEND

# pylint: disable=no-name-in-module
from .encrypt import PasswordEncryptor
from .tinxycloud import TinxyCloud, TinxyHostConfiguration

_LOGGER = logging.getLogger(__name__)

HEADERS = {"Content-Type": "application/json"}


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
        """Authenticate with the host."""
        api = TinxyCloud(
            host_config=TinxyHostConfiguration(
                api_token=api_key, api_url=TINXY_BACKEND
            ),
            web_session=web_session,
        )
        await api.sync_devices()
        return True

    async def _validate_response(self, endpoint, response):
        """Validate HTTP response from the device."""
        if response.status == 200:
            return await response.json(content_type=None)
        if response.status == 400:
            _LOGGER.error(
                "Request failed at %s with status %d", endpoint, response.status
            )
            raise TinxyConnectionException(f"Request error: status {response.status}")
        return None

    async def _send_request(
        self, method: str, endpoint: str, payload=None, web_session=None
    ):
        """Handle HTTP requests and error checking."""
        url = f"{self.host}{endpoint}"
        try:
            async with web_session.request(
                method,
                url=url,
                json=payload if method == "POST" else None,
                headers=HEADERS,
            ) as response:
                return await self._validate_response(endpoint, response)
        except TimeoutError as e:
            _LOGGER.error("Request to %s timed out", url)
            raise TinxyConnectionException("Request timed out") from e
        except aiohttp.ClientError as e:
            _LOGGER.error("Client error for request to %s: %s", url, e)
            raise TinxyConnectionException("Client error occurred") from e
        except Exception as e:
            _LOGGER.error("Error for request to %s: %s", url, e)
            raise TinxyConnectionException("Error occurred") from e

    @Throttle(timedelta(seconds=1))
    async def tinxy_toggle(
        self, mqttpass: str, relay_number: int, action: int, web_session
    ) -> bool:
        """Toggle Tinxy device state."""
        if action not in [0, 1]:
            _LOGGER.error("Action must be 0 (off) or 1 (on): %s", action)
            return False

        payload = {
            "password": PasswordEncryptor(mqttpass).generate_password(),
            "relayNumber": relay_number,
            "action": str(action),
        }

        try:
            return await self._send_request("POST", "/toggle", payload, web_session)
        except TinxyConnectionException as e:
            _LOGGER.error("Error toggling device relay %s: %s", relay_number, e)
            return False

    async def fetch_device_data(self, node, web_session):
        """Fetch and decode device data."""
        try:
            device_data = await self._send_request(
                "GET", "/info", web_session=web_session
            )
            return self._decode_device_data(device_data, node)
        except TinxyConnectionException as e:
            _LOGGER.error("Failed to update status for node %s: %s", node["name"], e)
            raise TinxyLocalException(
                "Error fetching device data, TinxyConnectionException"
            ) from e
        except Exception as e:
            _LOGGER.error("Error fetching device data: %s", e)
            raise TinxyLocalException("Error fetching device data, Exception") from e

    @staticmethod
    def _decode_device_data(data, node):
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
                    device["brightness"] = int(brightness_array[index] or "000", 10)

        decoded_data["devices"] = state_array
        return decoded_data
