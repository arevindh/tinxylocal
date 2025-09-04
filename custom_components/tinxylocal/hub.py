"""Module for interacting with Tinxy devices locally."""

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, Optional

import aiohttp
import platform

from .const import TINXY_BACKEND
from .tinxycloud import TinxyCloud, TinxyHostConfiguration

_LOGGER = logging.getLogger(__name__)

HEADERS = {"Content-Type": "application/json"}


@dataclass
class QueuedCommand:
    """Represents a queued command for a Tinxy device."""
    command_type: str  # 'toggle' or 'brightness'
    relay_number: int
    action: Optional[int] = None
    brightness: Optional[int] = None
    future: Optional[asyncio.Future] = None
    timestamp: float = 0.0
    
    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


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
        
        # Rate limiting configuration
        self.command_timeout = 30.0  # seconds
        self.queue_limit = 50  # max commands per device
        self.rate_limit_delay = 1.0  # seconds between commands
        
        # Per-device command queues and workers
        self.device_queues: Dict[str, deque] = {}
        self.device_workers: Dict[str, asyncio.Task] = {}
        self.device_last_command: Dict[str, float] = {}
        self._shutdown = False

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

    async def tinxy_set_brightness(
        self, mqttpass: str, relay_number: int, brightness: int) -> bool:
        """Set Tinxy device brightness using the CLI executable."""

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
            "-action", "1",  # Always turn on when setting brightness
            "-ip", self.ip_address,
            "-password", mqttpass,
            "-relay", str(relay_number),
            "-brightness", str(brightness),
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                _LOGGER.info("Successfully set brightness %s for relay %s", brightness, relay_number)
                return True
            else:
                _LOGGER.warning(
                    "Brightness control failed for relay %s (brightness: %s). Stderr: %s. Falling back to toggle.",
                    relay_number,
                    brightness,
                    stderr.decode().strip(),
                )
                # Fallback to simple toggle if brightness control is not supported
                return await self.tinxy_toggle(mqttpass, relay_number, 1)
        except Exception as e:
            _LOGGER.error("Failed to execute brightness command: %s. Falling back to toggle.", e)
            # Fallback to simple toggle if brightness control fails
            return await self.tinxy_toggle(mqttpass, relay_number, 1)

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
            "door": data.get("door"),
            "devices": [],
        }

        state_array = []
        for index, status in enumerate(data["state"]):
            device_info = node["devices"][index] if index < len(node["devices"]) else {"name": f"Device {index + 1}", "type": "Socket"}
            
            # Handle both dictionary and string formats for device info
            if isinstance(device_info, dict):
                device_name = device_info.get("name", f"Device {index + 1}")
                device_type = device_info.get("type", "Socket")
            else:
                device_name = device_info
                device_type = node["deviceTypes"][index] if index < len(node.get("deviceTypes", [])) else "Socket"
            
            state_array.append({
                "name": device_name,
                "type": device_type,
                "status": "on" if status == "1" else "off",
            })

        if "bright" in data:
            brightness_array = [
                data["bright"][i : i + 3] for i in range(0, len(data["bright"]), 3)
            ]
            
            for index, device in enumerate(state_array):
                device_type = device["type"].lower()
                
                if device_type in ["light", "fan"]:
                    brightness_value = int(brightness_array[index] or "000", 10)
                    device["brightness"] = brightness_value

        decoded_data["devices"] = state_array
        return decoded_data

    @staticmethod
    def get_device_icon(device_type: str) -> str:
        """Generate an icon based on the device type."""
        # Icon mapping matching the cloud version
        icon_mapping = {
            "Heater": "mdi:radiator",
            "Tubelight": "mdi:lightbulb-fluorescent-tube",
            "LED Bulb": "mdi:lightbulb",
            "Dimmable Light": "mdi:lightbulb",
            "LED Dimmable Bulb": "mdi:lightbulb",
            "Music System": "mdi:music",
            "Fan": "mdi:fan",
            "Socket": "mdi:power-socket-eu",
            "TV": "mdi:television",
            "Lock": "mdi:lock",
        }
        
        return icon_mapping.get(device_type, "mdi:toggle-switch")

    async def queue_toggle_command(
        self, device_id: str, mqttpass: str, relay_number: int, action: int
    ) -> bool:
        """Queue a toggle command with rate limiting."""
        return await self._queue_command(
            device_id, mqttpass, "toggle", relay_number, action=action
        )

    async def queue_brightness_command(
        self, device_id: str, mqttpass: str, relay_number: int, brightness: int
    ) -> bool:
        """Queue a brightness command with rate limiting."""
        return await self._queue_command(
            device_id, mqttpass, "brightness", relay_number, brightness=brightness
        )

    async def _queue_command(
        self,
        device_id: str,
        mqttpass: str,
        command_type: str,
        relay_number: int,
        action: Optional[int] = None,
        brightness: Optional[int] = None,
        deduplicate: bool = True
    ) -> bool:
        """Queue a command for execution with rate limiting."""
        if self._shutdown:
            raise TinxyLocalException("Hub is shutting down")

        # Get or create device queue
        if device_id not in self.device_queues:
            self.device_queues[device_id] = deque()
            self.device_last_command[device_id] = 0.0
            # Start worker for this device
            self.device_workers[device_id] = asyncio.create_task(
                self._device_worker(device_id, mqttpass)
            )

        queue = self.device_queues[device_id]
        
        # Check queue limit
        if len(queue) >= self.queue_limit:
            _LOGGER.warning(
                "Command queue full for device %s (limit: %d)", 
                device_id, self.queue_limit
            )
            raise TinxyLocalException("Command queue full")

        # Deduplication: remove pending commands for the same relay
        if deduplicate:
            new_queue = deque()
            removed_count = 0
            
            while queue:
                cmd = queue.popleft()
                if cmd.relay_number == relay_number:
                    # Cancel the old command
                    if cmd.future and not cmd.future.done():
                        cmd.future.set_exception(
                            TinxyLocalException("Superseded by newer command")
                        )
                    removed_count += 1
                else:
                    new_queue.append(cmd)
            
            # Replace the queue
            self.device_queues[device_id] = new_queue
            queue = new_queue
            
            if removed_count > 0:
                _LOGGER.debug(
                    "Removed %d pending commands for device %s relay %d", 
                    removed_count, device_id, relay_number
                )

        # Create and queue the new command
        future = asyncio.Future()
        command = QueuedCommand(
            command_type=command_type,
            relay_number=relay_number,
            action=action,
            brightness=brightness,
            future=future
        )
        
        queue.append(command)
        
        # Log queue status
        queue_size = len(queue)
        if queue_size > 5:
            _LOGGER.info(
                "Command queue for device %s has %d pending commands", 
                device_id, queue_size
            )

        # Wait for command completion
        return await future

    async def _device_worker(self, device_id: str, mqttpass: str) -> None:
        """Background worker to process commands for a specific device."""
        _LOGGER.debug("Started command worker for device %s", device_id)
        
        while not self._shutdown:
            try:
                queue = self.device_queues.get(device_id)
                if not queue:
                    await asyncio.sleep(0.1)
                    continue

                # Check rate limiting
                last_command_time = self.device_last_command[device_id]
                time_since_last = time.time() - last_command_time
                
                if time_since_last < self.rate_limit_delay:
                    sleep_time = self.rate_limit_delay - time_since_last
                    await asyncio.sleep(sleep_time)

                # Get the next command
                command = queue.popleft()
                
                # Check if command has timed out
                if time.time() - command.timestamp > self.command_timeout:
                    _LOGGER.warning(
                        "Command timeout for device %s, relay %d", 
                        device_id, command.relay_number
                    )
                    if command.future and not command.future.done():
                        command.future.set_exception(
                            TinxyLocalException("Command timeout")
                        )
                    continue

                # Execute the command
                try:
                    if command.command_type == "toggle":
                        result = await self.tinxy_toggle(
                            mqttpass, command.relay_number, command.action
                        )
                    elif command.command_type == "brightness":
                        result = await self.tinxy_set_brightness(
                            mqttpass, command.relay_number, command.brightness
                        )
                    else:
                        result = False
                        _LOGGER.error("Unknown command type: %s", command.command_type)

                    # Update last command time
                    self.device_last_command[device_id] = time.time()

                    # Complete the future
                    if command.future and not command.future.done():
                        command.future.set_result(result)

                except Exception as e:
                    _LOGGER.error(
                        "Error executing command for device %s: %s", device_id, e
                    )
                    if command.future and not command.future.done():
                        command.future.set_exception(e)

            except asyncio.CancelledError:
                break
            except Exception as e:
                _LOGGER.error("Error in device worker for %s: %s", device_id, e)
                await asyncio.sleep(1)

        _LOGGER.debug("Stopped command worker for device %s", device_id)

    async def shutdown(self) -> None:
        """Shutdown the hub and stop all workers."""
        self._shutdown = True
        for worker in self.device_workers.values():
            if not worker.done():
                worker.cancel()
        await asyncio.gather(*self.device_workers.values(), return_exceptions=True)
