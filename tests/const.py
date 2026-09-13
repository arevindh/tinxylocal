"""Shared fixtures for the Tinxy Local tests.

The payloads here are the real shapes returned by a WIFI_2SWITCH_V1 on
firmware 82 and by the Tinxy cloud device list, not invented ones. `firmware`
and `version` really are integers, which is why the coordinator coerces them.
"""

from homeassistant.const import CONF_API_KEY, CONF_HOST

from custom_components.tinxylocal.const import (
    CONF_DEVICE,
    CONF_DEVICE_ID,
    CONF_MQTT_PASS,
)

HOST = "10.0.28.17"
CHIP_ID = "11509299"
DEVICE_ID = "669b9361c3ff9afe7633de52"
API_KEY = "tinxy-test-token"
MQTT_PASS = "a1b2c3d4e5"

# GET /info, exactly as the device answers
DEVICE_INFO = {
    "rssi": -60,
    "ip": HOST,
    "version": 82,
    "status": 1,
    "state": "00",
    "chip_id": CHIP_ID,
    "ssid": "SmartThings",
    "firmware": 82,
    "model": "WIFI_2SWITCH_V1",
}

DEVICE_INFO_ON = {**DEVICE_INFO, "state": "10"}

# A 3-gang + fan unit, for the features-vs-deviceTypes split
FAN_INFO = {
    **DEVICE_INFO,
    "chip_id": "3804120",
    "state": "1000",
    "bright": "100100000000",
    "model": "WIFI_3SWITCH_1FAN",
}

# One entry from the cloud v2/devices list. Relay 2 is LABELLED "Fan" by the
# user while `features` reports SWITCH: the case where features must win.
CLOUD_DEVICE = {
    "_id": DEVICE_ID,
    "name": "Hall",
    "devices": ["LED", "Fan"],
    "deviceTypes": ["LED Bulb", "Fan"],
    "mqttPassword": MQTT_PASS,
    "uuidRef": {"uuid": CHIP_ID},
    "typeId": {
        "name": "WIFI_2SWITCH_V1",
        "long_name": "Tinxy 2 Node Switch",
        "gtype": "action.devices.types.SWITCH",
        "traits": ["action.devices.traits.OnOff"],
        "features": ["SWITCH", "SWITCH"],
        "numberOfRelays": 2,
    },
    "firmwareVersion": 82,
}

CLOUD_LOCK = {
    "_id": "60a1b2c3d4e5f60718293a4b",
    "name": "Front Door",
    "devices": [],
    "deviceTypes": ["Lock"],
    "mqttPassword": MQTT_PASS,
    "uuidRef": {"uuid": "5610150"},
    "typeId": {
        "name": "WIRED_DOOR_LOCK",
        "long_name": "Tinxy Wired Door Lock",
        "gtype": "action.devices.types.LOCK",
        "traits": ["action.devices.traits.LockUnlock"],
        "features": ["LOCK"],
        "numberOfRelays": 1,
    },
    "firmwareVersion": 82,
}

CLOUD_DEVICES = [CLOUD_DEVICE, CLOUD_LOCK]

ENTRY_DATA = {
    CONF_DEVICE: CLOUD_DEVICE,
    CONF_HOST: HOST,
    CONF_MQTT_PASS: MQTT_PASS,
    CONF_DEVICE_ID: CHIP_ID,
    CONF_API_KEY: API_KEY,
}

INFO_URL = f"http://{HOST}/info"
TOGGLE_URL = f"http://{HOST}/toggle"
CLOUD_URL = "https://backend.tinxy.in/v2/devices/"
