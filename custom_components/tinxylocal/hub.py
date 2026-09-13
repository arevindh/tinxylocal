"""Module for interacting with Tinxy devices locally."""

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, Optional

import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DEFAULT_RATE_LIMIT_DELAY, DEFAULT_REQUEST_TIMEOUT, TINXY_BACKEND
from .crypto import encrypt_tinxy_payload
from .tinxycloud import TinxyCloud, TinxyHostConfiguration

_LOGGER = logging.getLogger(__name__)

HEADERS = {"Content-Type": "application/json", "Connection": "close"}


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


class TinxyCommandSuperseded(TinxyLocalException):
    """A newer command for the same relay replaced this one before it ran.

    Expected whenever a switch is operated twice in quick succession. The newer
    command carries the state the user asked for, so this must not surface as an
    error.
    """


class TinxyLocalHub:
    """TinxyLocalHub class for interacting with Tinxy devices locally."""
    def __init__(
        self,
        hass,
        host: str,
        request_timeout: int = DEFAULT_REQUEST_TIMEOUT,
        rate_limit_delay: float = DEFAULT_RATE_LIMIT_DELAY,
    ) -> None:
        """Initialize with Home Assistant instance and the device host."""
        self.hass = hass
        self.host = f"http://{host}"
        self.ip_address = host
        self.request_timeout = request_timeout
        
        # Rate limiting configuration
        self.command_timeout = 30.0  # seconds
        self.queue_limit = 50  # max commands per device
        self.rate_limit_delay = rate_limit_delay  # seconds between commands
        
        # Per-device command queues and workers
        self.device_queues: Dict[str, deque] = {}
        self.device_workers: Dict[str, asyncio.Task] = {}
        self.device_last_command: Dict[str, float] = {}
        self.last_command_timestamp = 0
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

    async def get_info(self, web_session) -> dict | None:
        """Return the raw /info payload, or None if the device did not answer with one."""
        response = await self._send_request("GET", "/info", web_session=web_session)
        return response if isinstance(response, dict) else None

    async def validate_ip(self, web_session, chip_id=None) -> str:
        """Validate the device's local API by checking the /info endpoint.

        Returns:
            str: Status string indicating the result of the IP validation.
                 - "ok" if the response is 200 and accessible.
                 - "api_not_available" if the response is 400.
                 - "connection_error" for other errors or no response.

        """
        try:
            response = await self.get_info(web_session)
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
                timeout=aiohttp.ClientTimeout(total=self.request_timeout),
            ) as response:
                if response.status == 200:
                    return await response.json(content_type=None)
                if response.status == 400:
                    handle_exception(
                        f"Device at {url} rejected the request (HTTP 400). Check that "
                        "the device key is correct in the integration options.",
                        None,
                    )
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
        self, mqttpass: str, relay_number: int, action: int
    ) -> bool:
        """Toggle a relay via the device's local HTTP API."""
        if action not in (0, 1):
            _LOGGER.error("Action must be 0 (off) or 1 (on): %s", action)
            return False
        return await self._send_command(mqttpass, relay_number, action)

    async def tinxy_set_brightness(
        self, mqttpass: str, relay_number: int, brightness: int
    ) -> bool:
        """Set relay brightness/fan speed via the device's local HTTP API."""
        if not 0 <= brightness <= 100:
            _LOGGER.error("Brightness must be between 0 and 100: %s", brightness)
            return False
        # Setting a brightness always implies turning the relay on.
        return await self._send_command(mqttpass, relay_number, 1, brightness)

    async def _send_command(
        self,
        mqttpass: str,
        relay_number: int,
        action: int,
        brightness: int | None = None,
    ) -> bool:
        """POST an XXTEA-authenticated command to the device.

        The device authenticates a command by decrypting the unix timestamp with
        its own copy of the mqtt password, so the timestamp must be strictly
        increasing or the firmware rejects the request as a replay (HTTP 400).
        """
        now_ts = max(int(time.time()), self.last_command_timestamp + 1)
        self.last_command_timestamp = now_ts

        payload = {
            "password": encrypt_tinxy_payload(mqttpass, timestamp=now_ts),
            "action": str(action),
            "relayNumber": relay_number,
        }
        if brightness is not None:
            payload["brightness"] = brightness

        web_session = async_get_clientsession(self.hass)
        response = await self._send_request(
            "POST", "/toggle", payload=payload, web_session=web_session
        )
        return response is not None

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

        # Deduplication: drop pending commands for the same relay.
        #
        # This MUST mutate the existing deque rather than build a replacement.
        # The worker holds its own reference to this object across the rate-limit
        # sleep below, so swapping `device_queues[device_id]` for a new deque
        # leaves the worker popping from an orphaned, now-empty one:
        # "pop from an empty deque", a lost second of latency, and an error in
        # the log every time a second switch on the same device is operated
        # mid-sleep.
        if deduplicate:
            superseded = [cmd for cmd in queue if cmd.relay_number == relay_number]
            if superseded:
                kept = [cmd for cmd in queue if cmd.relay_number != relay_number]
                queue.clear()
                queue.extend(kept)
                for cmd in superseded:
                    if cmd.future and not cmd.future.done():
                        cmd.future.set_exception(
                            TinxyCommandSuperseded("Superseded by newer command")
                        )
                _LOGGER.debug(
                    "Dropped %d pending command(s) for device %s relay %d",
                    len(superseded), device_id, relay_number,
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

                # A supersede during that sleep can empty the queue.
                if not queue:
                    continue

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
