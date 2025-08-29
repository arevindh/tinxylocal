"""Module for interacting with Tinxy devices locally."""

import logging

import aiohttp
import asyncio 

from .const import TINXY_BACKEND

from .tinxycloud import TinxyCloud, TinxyHostConfiguration
import platform

_LOGGER = logging.getLogger(__name__)

HEADERS = {"Content-Type": "application/json"}


class TinxyConnectionException(Exception):
    """Exception for connection errors with Tinxy devices."""


class TinxyLocalException(Exception):
    """General exception for Tinxy local device errors."""


class TinxyLocalHub:
    """TinxyLocalHub class for interacting with Tinxy devices locally."""
    def __init__(self, hass, host: str) -> None:
        """Initialize with Home Assistant instance and the device host."""
        self.hass = hass
        self.host = f"http://{host}"
        self.ip_address = host

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

    async def validate_ip(self, web_session, chip_id=None) -> str:
        """Validate the device's local API by checking the /info endpoint.

        Returns:
            str: Status string indicating the result of the IP validation.
                 - "ok" if the response is 200 and accessible.
                 - "api_not_available" if the response is 400.
                 - "connection_error" for other errors or no response.

        """
        try:
            response = await self._send_request("GET", "/info", web_session=web_session)
            if response is not None:
                if chip_id:
                    if response["chip_id"] == chip_id:
                        return "ok"
                    return "wrong_chip_id"
                return "ok"
            return "api_not_available"  # noqa: TRY300
        except TinxyConnectionException as _e:
            return "connection_error"

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

        def handle_exception(message: str, exception: Exception | None):
            _LOGGER.error(message)
            raise TinxyConnectionException(message) from exception

        try:
            async with web_session.request(
                method,
                url=url,
                json=payload if method == "POST" else None,
                headers=HEADERS,
                timeout=2,
            ) as response:
                if response.status == 200:
                    return await response.json(content_type=None)
                if response.status == 400:
                    handle_exception(f"Request error: status {response.status}", None)
                else:
                    handle_exception(
                        f"Unexpected error: status {response.status}", None
                    )
        except TimeoutError as e:
            handle_exception(f"Request to {url} timed out", e)
        except aiohttp.ClientError as e:
            handle_exception(f"Client error for request to {url}: {e}", e)
        except Exception as e:  # noqa: BLE001
            handle_exception(f"Error for request to {url}: {e}", e)

    async def tinxy_toggle(
        self, mqttpass: str, relay_number: int, action: int) -> bool:
        """Toggle Tinxy device state using the CLI executable."""
        if action not in [0, 1]:
            _LOGGER.error("Action must be 0 (off) or 1 (on): %s", action)
            return False

        action_str = "on" if action == 1 else "off"

        INTEGRATION_PATH = self.hass.config.path(f"custom_components/tinxylocal/build")
        # Determine the correct executable based on the system architecture
        system_arch = platform.machine()
        arch_table = {
            "x86_64": ["x64", "x86_64", "amd64", "intel"],
            "armv7l": ["armv7l"],
            "armv6l": ["armv6l"],
            "aarch64": ["aarch64", "arm64"],
            "win": ["win"],
        }

        executable_path = None
        for arch, aliases in arch_table.items():
            if system_arch in aliases or system_arch.startswith(arch):
                if arch == "x86_64":
                    executable_path = f"{INTEGRATION_PATH}/tinxy-cli_linux_amd64"
                elif arch == "armv7l":
                    executable_path = f"{INTEGRATION_PATH}/tinxy-cli_linux_armv7"
                elif arch == "armv6l":
                    executable_path = f"{INTEGRATION_PATH}/tinxy-cli_linux_armv6"
                elif arch == "aarch64":
                    executable_path = f"{INTEGRATION_PATH}/tinxy-cli_linux_arm64"
                elif arch == "win":
                    executable_path = f"{INTEGRATION_PATH}/tinxy-cli_windows_amd64.exe"
                break

        if not executable_path:
            _LOGGER.error("Unsupported system architecture: %s", system_arch)
            return False

        command = [
            executable_path,
            "-action", str(action),
            "-ip", self.ip_address,
            "-password", mqttpass,
            "-relay", str(relay_number),
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                _LOGGER.info("Successfully toggled relay %s to %s", relay_number, action_str)
                return True
            else:
                _LOGGER.error(
                    "Error toggling relay %s to %s. Stderr: %s",
                    relay_number,
                    action_str,
                    stderr.decode().strip(),
                )
                return False
        except Exception as e:
            _LOGGER.error("Failed to execute toggle command: %s", e)
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

    @staticmethod
    def get_device_icon(device_type: str) -> str:
        """Generate an icon based on the device type."""
        if device_type == "Heater":
            return "mdi:radiator"
        if device_type == "Tubelight":
            return "mdi:lightbulb-fluorescent-tube"
        if device_type in ["LED Bulb", "Dimmable Light", "LED Dimmable Bulb"]:
            return "mdi:lightbulb"
        if device_type == "Music System":
            return "mdi:music"
        if device_type == "Fan":
            return "mdi:fan"
        if device_type == "Socket":
            return "mdi:power-socket-eu"
        if device_type == "TV":
            return "mdi:television"
        if device_type == "Lock":
            return "mdi:lock"
        return "mdi:toggle-switch"
