from dataclasses import dataclass
from pprint import pprint


class TinxyException(Exception):
    """Tinxy Exception."""

    def __init__(self, message="Failed") -> None:
        """Init."""
        self.message = message
        super().__init__(self.message)


class TinxyAuthenticationException(TinxyException):
    """Tinxy authentication exception."""


@dataclass
class TinxyHostConfiguration:
    """Tinxy host configuration."""

    api_token: str
    api_url: str | None

    def __post_init__(self):
        if self.api_token is None:
            raise TinxyAuthenticationException(
                message="No api token to the was provided."
            )
        if self.api_token is None and self.api_url is None:
            raise TinxyException(
                message="No  url, api token to the Tinxy server was provided."
            )


class TinxyCloud:
    """Tinxy Cloud."""

    DOMAIN = "tinxy"
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
    typeId_fan = ["WIFI_3SWITCH_1FAN", "Fan", "WIFI_SWITCH_1FAN_V1"]

    def __init__(self, host_config: TinxyHostConfiguration, web_session) -> None:
        """Init."""
        self.host_config = host_config
        self.web_session = web_session

    async def tinxy_request(self, path, payload=None, method="GET"):
        """Tinxy API request."""

        pprint("new request to " + path)

        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + self.host_config.api_token,
        }
        if payload:
            payload["source"] = "Home Assistant"

        # async with self.web_session as session:
        # try:
        async with self.web_session.request(
            method=method,
            url=self.host_config.api_url + path,
            json=payload,
            headers=headers,
        ) as resp:
            return await resp.json()
            # except:
            #     raise TinxyException(message="API [GET] call failed")

    async def get_device_list(self):
        """Read all devices from server."""
        return await self.tinxy_request("v2/devices/")

    async def get_devices_pass(self):
        """Read all devices from server."""

        data = await self.tinxy_request("v2/devices/")
        filtered_items = {
            item["_id"]: {
                "mqttPassword": item["mqttPassword"],
                "uuid": item["uuidRef"]["uuid"],
                "name": item["name"],
            }
            for item in data
            if "mqttPassword" in item
            and "uuidRef" in item
            and "uuid" in item["uuidRef"]
        }
        return filtered_items

    async def sync_devices(self):
        """Read all devices from server."""
        device_list = []
        result = await self.tinxy_request("v2/devices/")
        for item in result:
            device_list = device_list + (self.parse_device(item))
        self.devices = device_list
        return True

    def list_switches(self):
        """List switches."""
        return [d for d in self.devices if d["device_type"] == "Switch"]

    def list_lights(self):
        """List light."""
        return [d for d in self.devices if d["device_type"] == "Light"]

    def list_all_devices(self):
        return self.devices

    def list_fans(self):
        """List fans."""
        return [d for d in self.devices if d["device_type"] == "Fan"]

    def list_locks(self):
        """List lokcs."""
        return [d for d in self.devices if d["gtype"] in self.gtype_lock]

    async def get_device_state(self, id, device_number):
        """Get device state."""
        return await self.tinxy_request(
            "v2/devices/" + id + "/state?deviceNumber=" + device_number
        )

    def state_to_val(self, state):
        """State to value."""
        if state == "ON":
            return True
        return False

    async def get_all_status(self):
        """Get sstatus of all devices."""
        status_data = await self.tinxy_request("v2/devices_state")
        device_status = {}
        for status in status_data:
            if "state" in status:
                single_device = {}
                if type(status["state"]).__name__ == "list":
                    for item in status["state"]:
                        single_device = {}
                        if "number" in item:
                            device_id = status["_id"] + "-" + str(item["number"])
                        else:
                            device_id = status["_id"] + "-1"
                            single_device["item"] = item
                        if "state" in item["state"]:
                            single_device["state"] = self.state_to_val(
                                item["state"]["state"]
                            )
                        if "status" in item["state"]:
                            single_device["status"] = item["state"]["status"]
                        if "brightness" in item["state"]:
                            single_device["brightness"] = item["state"]["brightness"]
                        device_status[device_id] = single_device
                else:
                    single_device = {}
                    device_id = status["_id"] + "-1"
                    if "state" in status["state"]:
                        single_device["state"] = self.state_to_val(
                            status["state"]["state"]
                        )
                    if "status" in status["state"]:
                        single_device["status"] = status["state"]["status"]
                    if "brightness" in status["state"]:
                        single_device["brightness"] = status["state"]["brightness"]
                    device_status[device_id] = single_device

        return device_status

    async def set_device_state(self, itemid, device_number, state, brightness=None):
        """Set device state."""
        payload = {"request": {"state": state}, "deviceNumber": device_number}
        # check if brightness is provided
        if brightness is not None:
            payload["request"]["brightness"] = brightness
        return await self.tinxy_request(
            "v2/devices/" + itemid + "/toggle", payload=payload, method="POST"
        )

    def get_device_info(self, device):
        """Parse device info."""
        return {
            "identifiers": {
                # Serial numbers are unique identifiers within a specific domain
                (self.DOMAIN, device["_id"])
            },
            "name": device["name"],
            "manufacturer": "Tinxy.in",
            "model": device["typeId"]["long_name"],
            "sw_version": device["firmwareVersion"],
            # "via_device": (hue.DOMAIN, self.api.bridgeid),
        }

    def parse_device(self, data):
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

    def get_device_type(self, tinxy_type, itemid):
        """Generate device type."""
        light_list = ["Tubelight", "LED Bulb"]
        if tinxy_type in self.typeId_fan and itemid == 0:
            return "Fan"
        elif tinxy_type in light_list:
            return "Light"
        elif tinxy_type in self.gtype_lock:
            return "Switch"
        else:
            return "Switch"

    def icon_generate(self, devicetype):
        """Generate icon name."""
        if devicetype == "Heater":
            return "mdi:radiator"
        elif devicetype == "Tubelight":
            return "mdi:lightbulb-fluorescent-tube"
        elif devicetype in (
            "LED Bulb",
            "Dimmable Light",
            "LED Dimmable Bulb",
            "EVA_BULB",
        ):
            return "mdi:lightbulb"
        elif devicetype == "Music System":
            return "mdi:music"
        elif devicetype == "Fan":
            return "mdi:fan"
        elif devicetype == "Socket":
            return "mdi:power-socket-eu"
        elif devicetype == "TV":
            return "mdi:television"
        else:
            return "mdi:toggle-switch"
