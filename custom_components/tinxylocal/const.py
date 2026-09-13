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
# Spacing between commands to one device. This is a protocol floor, not a comfort
# setting: the auth token encrypts a unix timestamp in WHOLE SECONDS, and the device
# rejects any timestamp that does not exceed the highest one it has already seen.
# Two commands inside the same second therefore cannot both be authenticated, and
# the limit is per DEVICE, not per relay. Verified on WIFI_2SWITCH_V1 firmware 82:
# a second command 0.25s later on a different relay returns HTTP 400.
# Going faster only appears to work by dating the timestamp into the future, which
# the device accepts but then treats as its new high-water mark, locking out every
# honestly-dated command until real time catches up. Measured: sending now+30
# rendered the device unresponsive to normal commands for the next 30 seconds.
DEFAULT_RATE_LIMIT_DELAY = 1.0

CONF_ACTION = "action"
CONF_ADD_DEVICE = "add_device"
CONF_EDIT_DEVICE = "edit_device"
CONF_SETUP_CLOUD = "setup_cloud"
CONF_NO_CLOUD = "no_cloud"
CONF_DEVICE = "device"
