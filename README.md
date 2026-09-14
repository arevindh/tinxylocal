# Tinxy Local

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=flat-square)](https://github.com/hacs/integration)
[![Version](https://img.shields.io/github/v/release/arevindh/tinxylocal?style=flat-square)](https://github.com/arevindh/tinxylocal/releases)

Control **Tinxy smart switches, fan controllers and door locks** directly over your home Wi-Fi
from Home Assistant. No cloud round trip, no MQTT broker, no polling someone else's server.

Your Tinxy account is used **once, during setup**, to look up each device's local key. After that
every status read and every command goes straight to the device on your LAN.

Join the [Discord server](https://discord.gg/VH4jgz2f) for support.

---

## Contents

1. [Requirements](#requirements)
2. [Before you start](#before-you-start)
3. [Installation](#installation)
4. [Adding your devices](#adding-your-devices)
5. [What you get](#what-you-get)
6. [Settings](#settings)
7. [Supported hardware](#supported-hardware)
8. [Upgrading from 2.x](#upgrading-from-2x)
9. [Troubleshooting](#troubleshooting)
10. [How it works](#how-it-works)

---

## Requirements

| | |
|---|---|
| Home Assistant | 2025.4.0 or newer |
| Devices | Tinxy devices with **local HTTP control enabled** |
| Network | Home Assistant and your devices on the same LAN |
| Dependencies | None. Pure Python, nothing extra installed |

> [!IMPORTANT]
> **Tinxy EVA bulbs are not supported.** They talk to an EVA hub over a proprietary RF mesh
> and have no local Wi-Fi address of their own. The `EVA_HUB` itself may appear during
> discovery: do not add it.

---

## Before you start

### Getting your API token

In the Tinxy mobile app, tap the **menu icon (☰)** and select **API Token**.

### Checking a device supports local control

Visit `http://<device-ip>/info` in a browser. A working device returns something like:

```json
{"rssi":-60,"ip":"10.0.28.17","version":82,"status":1,"state":"00",
 "chip_id":"11509299","ssid":"YourWiFi","firmware":82,"model":"WIFI_2SWITCH_V1"}
```

If you get no response, local control is not enabled on that device and this integration
cannot use it.

> [!CAUTION]
> ### Keep your credentials private
>
> - **Tinxy API tokens never expire and cannot be revoked from the app.** If one leaks, the only
>   way to invalidate it is to create a brand new Tinxy account. Never paste one into a GitHub
>   issue, forum post, or log excerpt.
> - **Device keys also never expire.** The only way to change one is to remove and re-pair the
>   physical device in the Tinxy app.
>
> Both are stored in Home Assistant's `.storage` directory in plain text, which is normal for
> Home Assistant but worth knowing.

---

## Installation

### Via HACS (recommended)

1. In Home Assistant, open **HACS**.
2. Add `https://github.com/arevindh/tinxylocal` as a custom repository, category **Integration**.
3. Install **Tinxy Local**.
4. **Restart Home Assistant.**

### Manually

Copy `custom_components/tinxylocal/` into your Home Assistant `config/custom_components/`
directory, then restart.

---

## Adding your devices

Each device is added as its own entry. Repeat for each one you want in Home Assistant.

### Automatic discovery

Tinxy devices announce themselves over mDNS, so Home Assistant usually finds them on its own.
Look for a **Discovered Tinxy device** card under
**Settings → Devices & Services**, enter your API token, and submit. The integration matches
the device against your account and fetches its local key for you.

If you have already added one device, the token is remembered and discovery becomes a single
click for the rest.

### Manual setup

If discovery does not find a device (some networks block mDNS across VLANs):

1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for **Tinxy Local**.
3. Enter your API token, or reuse a saved one.
4. Pick the device from the list and enter its **local IP address**.

Setup fails deliberately if the IP does not belong to the device you selected, so a typo
cannot silently attach you to the wrong switch.

> [!TIP]
> Give your Tinxy devices static DHCP leases on your router. If an address does change,
> discovery will pick up the new one automatically and update the existing entry.

---

## What you get

### Controls

| Device type | Entity | Behaviour |
|---|---|---|
| Switch / socket / light | `switch` | On / off |
| Fan | `fan` | On / off plus three speeds (33%, 66%, 100%) |
| Door lock | `lock` | Unlock pulse. The device re-locks on its own timer |

Switches respond immediately in the dashboard: the new state shows at once while the command
is on its way, then reconciles with whatever the device actually reports.

### Diagnostics

Every device also gets three diagnostic sensors:

| Sensor | Default |
|---|---|
| IP address | Enabled |
| Wi-Fi network (SSID) | Enabled |
| Wi-Fi signal (dBm) | **Disabled** |

Wi-Fi signal is disabled on purpose. It changes on almost every poll, so leaving it on writes
a large number of rows to your recorder database for very little benefit. Enable it from the
device page if you are chasing down a signal problem.

---

## Settings

Open the device, then **⋮ → Reconfigure** (or the **Configure** button) to change:

| Setting | Default | What it does |
|---|---|---|
| Device IP address | | Where to reach the device |
| API key | | Used only to re-validate your account |
| Request timeout | `5s` | How long to wait for a device to answer |
| Polling interval | `6s` | How often status is refreshed. Must be at least the timeout |
| Command spacing | `1s` | Minimum gap between commands to one device. See below |

> [!WARNING]
> **One second is the floor, not a preference.** A device accepts at most one command per
> second, and that limit applies **per device, not per switch**: toggling two relays on the
> same unit back to back is exactly the case that fails. This is why the setting will not go
> lower. Raise it if a device is unreliable; do not try to work around it.
>
> Only commands are affected. Status polling is a separate, unrestricted read and stays as
> responsive as your polling interval allows.

---

## Supported hardware

Verified on real devices:

| Model | Verified |
|---|---|
| `WIFI_2SWITCH_V1` | Relay control, diagnostics, discovery |
| `WIFI_3SWITCH_1FAN` | Status and fan speed reporting |

Also supported:

`WIFI_SWITCH` · `WIFI_SWITCH_V2` · `WIFI_SWITCH_V3` · `WIFI_2SWITCH_V3` · `WIFI_4SWITCH` ·
`WIFI_4SWITCH_V2` · `WIFI_4SWITCH_V3` · `WIFI_6SWITCH_V1` · `WIFI_6SWITCH_V3` ·
`WIFI_3SWITCH_1FAN_V3` · `WIFI_SWITCH_1FAN_V1` · `Fan` · `WIFI_4DIMMER` · `Dimmable Light` ·
`WIFI_BULB_WHITE_V1` · `EM_DOOR_LOCK` · `WIRED_DOOR_LOCK` · `WIRED_DOOR_LOCK_V2` ·
`WIRED_DOOR_LOCK_V3`

Models not listed are not blocked. Any Tinxy device with local HTTP control enabled should
work. The list above records what has been tested, not a hard limit.

---

## Upgrading from 2.x

Upgrade in place. Your existing devices, entities, history and automations are unchanged.

**What happens automatically:**

- The bundled Go binaries (about 34 MB) are gone. Everything they did is now pure Python.
- Existing devices are tagged with their chip ID so discovery recognises them instead of
  offering them again as new.
- Command spacing is unchanged at `1s`, and is now adjustable in settings.

**Two changes you will notice:**

1. **Unreachable devices now show as unavailable** instead of displaying their last known
   state forever. If a device was quietly dropping offline before, you will start seeing it.
2. **Failed commands now report an error** in the interface rather than failing silently.

Neither is a regression. Both make problems visible that were previously hidden.

---

## Troubleshooting

### The device does not appear during discovery

Check `http://<device-ip>/info` in a browser first. No response means local control is not
enabled on the device. If `/info` works but discovery does not find it, mDNS is probably
blocked between Home Assistant and the device: use manual setup instead.

### "Device rejected the request (HTTP 400)"

The device did not accept the command. Usually the device key is wrong, which happens if the
device was re-paired in the Tinxy app after being added here. Re-add the device to fetch the
current key.

### A device stops responding after rapid toggling

This is the firmware lock-up described under [Settings](#settings). Power cycle the device,
then raise **Command spacing**.

### Entities show as unavailable

The device is not answering within the timeout. Check its Wi-Fi signal using the diagnostic
sensor. Weak signal (below about -80 dBm) may need a higher **Request timeout**.

### Starting over

Remove the integration from **Settings → Devices & Services**. If something is badly stuck,
delete `custom_components/tinxylocal/` from your configuration directory and restart.

---

## How it works

**Status** is read with a plain, unauthenticated request that returns relay states, per
relay brightness, signal strength and firmware details. Reads are unrestricted, so
polling is fast and is not affected by the command spacing below.

**Commands** are authenticated, and a device accepts at most **one per second**. That
limit is per device, not per relay, which is why the setting will not go lower and why
toggling two relays on the same unit takes about two seconds. Commands are queued and
spaced automatically; reads are not queued.

Earlier versions shelled out to a bundled Go program for this, shipping five compiled
binaries for different CPU architectures. That is now about 70 lines of Python using
nothing outside the standard library, producing identical output.

## Credits

Maintained by [@arevindh](https://github.com/arevindh).

### AI assistance

Parts of this codebase were reviewed and rewritten with [Claude Code](https://claude.ai/code),
covering the removal of the bundled Go binaries, the pure-Python rewrite of the local
authentication, mDNS discovery, the diagnostic sensors, and this documentation.

Every change was manually reviewed by the code owner and verified against real Tinxy hardware
before release. Nothing here was merged unreviewed.

### Upstream work

Parts of this integration come from the [ha-tinxylocal](https://github.com/selvakk2k/ha-tinxylocal)
fork by [@selvakk2k](https://github.com/selvakk2k), which showed that the local authentication
could be done in pure Python and so made the bundled Go binaries unnecessary. Their work is the
basis of:

- `crypto.py`, the local authentication, adapted directly
- the diagnostic sensor set, reworked here into one description-driven class
- the optimistic-update approach for instant dashboard feedback
- the command-spacing guard and `Connection: close` handling
- the credential guidance above, and the note that EVA bulbs cannot be reached
  locally: both were first documented in their README

Licensed under the terms in [LICENSE](LICENSE).
