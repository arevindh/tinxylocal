"""Tinxy Local."""

from dataclasses import dataclass

# pylint: disable=no-name-in-module
from .encrypt import PasswordEncryptor


class TinxyLocalException(Exception):
    """Tinxy Exception."""

    def __init__(self, message="Failed") -> None:
        """Init."""
        self.message = message
        super().__init__(self.message)


class TinxyAuthenticationException(TinxyLocalException):
    """Tinxy authentication exception."""


@dataclass
class TinxyLocalHostConfiguration:
    """Tinxy host configuration."""

    device_id: str
    api_token: str
    mqtt_pass: str
    host: str

    def __post_init__(self):
        """Post init."""
        if self.api_token is None or self.mqtt_pass is None:
            raise TinxyAuthenticationException(
                message="No API token / Mattermost password to the was provided."
            )
        if self.device_id is None or self.host is None:
            raise TinxyLocalException(
                message="No valid device id / ip address provided."
            )


class TinxyLocal:
    """Main class for tinxy."""

    DOMAIN = "tinxy"
    CONF_MQTT_PASS = "mqtt_pass"
    CONF_API_TOKEN = "api_token"
    CONF_HOST = "host"

    devices = []
    disabled_devices = ["EVA_HUB"]
    enabled_list = [
        "Dimmable Light",
        "EM_DOOR_LOCK",
        "EVA_BULB",
        "Fan",
        "WIFI_2SWITCH_V1",
        "WIFI_2SWITCH_V3",
        "WIFI_3SWITCH_1FAN",
        "WIFI_3SWITCH_1FAN_V3",
        "WIFI_4DIMMER",
        "WIFI_4SWITCH",
        "WIFI_4SWITCH_V2",
        "WIFI_4SWITCH_V3",
        "WIFI_6SWITCH_V1",
        "WIFI_6SWITCH_V3",
        "WIFI_BULB_WHITE_V1",
        "WIFI_SWITCH",
        "WIFI_SWITCH_1FAN_V1",
        "WIFI_SWITCH_V2",
        "WIFI_SWITCH_V3",
        "WIRED_DOOR_LOCK",
        "WIRED_DOOR_LOCK_V2",
        "WIRED_DOOR_LOCK_V3",
    ]

    gtype_light = ["action.devices.types.LIGHT"]
    gtype_switch = ["action.devices.types.SWITCH"]
    gtype_lock = ["action.devices.types.LOCK"]
    typeid_fan = [
        "WIFI_3SWITCH_1FAN",
        "Fan",
        "WIFI_SWITCH_1FAN_V1",
        "WIFI_3SWITCH_1FAN_V3",
    ]

    def __init__(self, host_config: TinxyLocalHostConfiguration, web_session) -> None:
        """Init."""
        self.host_config = host_config
        self.web_session = web_session

    async def get_all_device_states(self, device_data):
        """Get all device statues."""
        info = await self.device_info(device_data)
        result = {}
        device_id = device_data["_id"]
        for index, digit in enumerate(info.state):
            key = f"{device_id}_{index+1}"
            result[key] = int(digit)
        return result

    async def toggle(self, relay_number: int, action: any) -> dict:
        """Turn on device."""
        action_str = str(action)

        password = PasswordEncryptor.generate_password(self.host_config.mqtt_pass)

        # Construct the payload with dynamic values.
        payload = {
            "password": password,
            "relayNumber": relay_number,
            "action": action_str,  # Ensuring action is passed as a string
        }
        toggle_result = await self.api_request("toggle", payload, method="POST")

    async def api_request(self, path: str, payload: dict, method="GET") -> dict:
        """Tinxy api requests requests."""

        password = PasswordEncryptor.generate_password(
            self.host_config[self.CONF_MQTT_PASS]
        )

        # Define the request headers.
        headers = {"Content-Type": "application/json"}

        if method == "POST":
            payload["password"] = password

        # Make the POST request to toggle the device state.
        async with self.web_session.request(
            method=method,
            url=f"{self.host_config.host}/{path}",  # Using f-string for clarity
            json=payload,
            headers=headers,
        ) as resp:
            # Check if the request was successful (HTTP status code 200).
            if resp.status == 200:
                # Return the JSON response directly.
                return await resp.json(content_type=None)
            # Log or handle unsuccessful request appropriately.
            return False

    async def sync_devices(self, tinxy_device: dict) -> bool:
        """Read all devices from server."""
        self.parse_device(tinxy_device)
        return True

    def list_switches(self):
        """List switches."""
        return [d for d in self.devices if d["device_type"] == "Switch"]

    def list_lights(self):
        """List light."""
        return [d for d in self.devices if d["device_type"] == "Light"]

    def list_all_devices(self):
        """List all devices."""
        return self.devices

    def list_fans(self):
        """List fans."""
        return [d for d in self.devices if d["device_type"] == "Fan"]

    def list_locks(self):
        """List locks."""
        return [d for d in self.devices if d["gtype"] in self.gtype_lock]

    async def device_info(self, device_data: dict):
        """Parse device info."""
        result = await self.api_request(path="info", payload=None, method="GET")
        # Sample Data
        # {
        #     "rssi": -67,
        #     "ip": "192.168.1.100",
        #     "version": 75,
        #     "status": 1,
        #     "state": "11",
        #     "chip_id": "777777",
        #     "ssid": "WiFi",
        #     "firmware": 75,
        #     "model": "WIFI_2SWITCH_V1",
        # }
        if result is not False:
            return result
        return False

    def parse_device(self, data: dict):
        """Parse device."""
        devices = []

        # Handle single item devices
        if not data["devices"]:
            # Handle eva EVA_BULB
            if (
                data["typeId"]["name"] in self.enabled_list
                and data["typeId"]["name"] == "EVA_BULB"
            ):
                device_type = (
                    "Light" if data["typeId"]["name"] == "EVA_BULB" else "Switch"
                )
                devices.append(
                    {
                        "id": data["_id"] + "-1",
                        "device_id": data["_id"],
                        "name": data["name"],
                        "relay_no": 1,
                        "gtype": data["typeId"]["gtype"],
                        "traits": data["typeId"]["traits"],
                        "device_type": device_type,
                        "user_device_type": device_type,
                        "device_desc": data["typeId"]["long_name"],
                        "tinxy_type": data["typeId"]["name"],
                        "icon": self.icon_generate(data["typeId"]["name"]),
                        "device": self.get_device_info(data),
                    }
                )
            # Handle single node devices
            elif data["typeId"]["name"] in self.enabled_list:
                device_type = self.get_device_type(data["typeId"]["name"], 0)
                devices.append(
                    {
                        "id": data["_id"] + "-1",
                        "device_id": data["_id"],
                        "name": data["name"],
                        "relay_no": 1,
                        "gtype": data["typeId"]["gtype"],
                        "traits": data["typeId"]["traits"],
                        "device_type": device_type,
                        "user_device_type": device_type,
                        "device_desc": data["typeId"]["long_name"],
                        "tinxy_type": data["typeId"]["name"],
                        "icon": self.icon_generate(device_type),
                        "device": self.get_device_info(data),
                        "mqtt_pass": data.get("mqttPassword"),  # Check if key exists
                        "device_uuid": data.get("uuidRef", {}).get("uuid"),
                    }
                )
            else:
                pass
                # print('unknown  ='+data['typeId']['name'])
                # print(self.enabled_list)
        # Handle multinode_devices
        elif data["typeId"]["name"] in self.enabled_list:
            for itemid, nodes in enumerate(data["devices"]):
                devices.append(
                    {
                        "id": data["_id"] + "-" + str(itemid + 1),
                        "device_id": data["_id"],
                        "name": data["name"] + " " + nodes,
                        "relay_no": itemid + 1,
                        "gtype": data["typeId"]["gtype"],
                        "traits": data["typeId"]["traits"],
                        "device_type": self.get_device_type(
                            data["typeId"]["name"], itemid
                        ),
                        "user_device_type": data["deviceTypes"][itemid],
                        "device_desc": data["typeId"]["long_name"],
                        "tinxy_type": data["typeId"]["name"],
                        "icon": self.icon_generate(data["deviceTypes"][itemid]),
                        "device": self.get_device_info(data),
                        "mqtt_pass": data.get("mqttPassword"),  # Check if key exists
                        "device_uuid": data.get("uuidRef", {}).get("uuid"),
                    }
                )
        else:
            print("unknown  =" + data["typeId"]["name"])
            # print(self.enabled_list)
        return devices
