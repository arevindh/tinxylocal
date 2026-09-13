# Finding device IP addresses

> [!NOTE]
> **You usually do not need this.** Home Assistant discovers Tinxy devices automatically over
> mDNS, and the setup flow fills in the address for you. See
> [Adding your devices](README.md#adding-your-devices).
>
> Use this script only when discovery cannot reach your devices, typically when Home Assistant
> and the devices sit on different VLANs or your network blocks mDNS.

`discover.py` scans your network for Tinxy devices, matches each one against your Tinxy
account, and prints its IP address along with whether local control is enabled.

## Running it

```bash
# One-time setup
sudo apt install python3-venv          # if you do not already have it
git clone https://github.com/arevindh/tinxylocal
cd tinxylocal
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run
python discover.py
```

Paste your Tinxy API token when prompted. Get it from the Tinxy mobile app under
**menu (☰) → API Token**.

```bash
deactivate                             # when you are done
```

## Reading the output

```
Service Name: tinxy3de52._http._tcp.local.
Address: 10.0.28.17
Supports local control: Yes
Port: 80
Device Name : Hall
--------------------------------------------------
```

**Supports local control: Yes** means the device is ready to add. **No** means its local API is
not enabled and this integration cannot control it.

Run the script from a machine on the **same network segment as your devices**. mDNS does not
cross subnets, which is the same reason Home Assistant may have missed them.

> [!CAUTION]
> Your API token never expires and cannot be revoked from the Tinxy app. Do not paste the
> script's output into a public issue without checking it first.
