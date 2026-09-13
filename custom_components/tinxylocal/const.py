"""Constants for the Tinxy Local integration."""

DOMAIN = "tinxylocal"

CONF_MQTT_PASS = "mqtt_pass"
CONF_DEVICE_ID = "device_id"
CONF_REQUEST_TIMEOUT = "request_timeout"
CONF_POLLING_INTERVAL = "polling_interval"
CONF_RATE_LIMIT_DELAY = "rate_limit_delay"
TINXY_BACKEND = "https://backend.tinxy.in/"

# 5s, not 3s: before 3.0.0 the coordinator built its own hubs and so polled with
# the hub's hardcoded 5s default, ignoring this setting entirely. Now that the
# configured value actually reaches polling, the default has to be the one that
# has been running in production -- 3s was only ever applied to commands, and
# tightening polling would push slow or weak-signal devices into unavailable.
DEFAULT_REQUEST_TIMEOUT = 5
DEFAULT_POLLING_INTERVAL = 6
# Spacing between commands to one device. This is a floor imposed by the device,
# not a comfort setting: it accepts at most one command per second, and the limit
# is per DEVICE rather than per relay. Verified on WIFI_2SWITCH_V1 firmware 82: a
# second command a quarter of a second later on a different relay is refused.
# Sending faster does not work and can leave a device refusing commands for a
# while afterwards, so do not lower this to match other integrations.
DEFAULT_RATE_LIMIT_DELAY = 1.0

CONF_ACTION = "action"
CONF_ADD_DEVICE = "add_device"
CONF_EDIT_DEVICE = "edit_device"
CONF_SETUP_CLOUD = "setup_cloud"
CONF_NO_CLOUD = "no_cloud"
CONF_DEVICE = "device"

# Icons by the relay type the owner picked in the Tinxy app. These are Home
# Assistant vocabulary, so they live here rather than in the tinxy package.
ICONS = {
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
