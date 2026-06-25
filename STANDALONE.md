# Stand-alone Sonoff collector

Run the SonoffLAN device layer as a small **Linux service**, **without Home
Assistant**. It reuses the integration's Home-Assistant-free transport core
(`custom_components/sonoff/core/ewelink`) and adds a thin runner.

- **`sonoff-collector login`** — the only step that contacts the eWeLink **cloud**:
  it downloads your device list (including each device's `devicekey`) and caches
  it locally.
- **`sonoff-collector run`** — the **service**. It is **purely local**: it loads
  the cached devices, listens on the LAN via mDNS, decrypts/collects device
  state, and logs it. It **never connects to eWeLink**.

- **`sonoff-collector mqtt-login` + `run`** — optionally forward all collected
  state to an **MQTT broker** with **Home Assistant auto-discovery**, and accept
  control commands back from HA (HA → MQTT → collector → device over the LAN).
  Still no eWeLink cloud at runtime.

## Requirements

- Python 3.10+
- Run on a host with **LAN multicast/mDNS** access to your Sonoff devices
  (same L2 network). The device firmware must expose its LAN interface
  (the eWeLink app's "LAN mode" / "Local control" enabled).

## Install

From a checkout of this repository (the collector lives under `standalone/` and
vendors its transport core, so it is self-contained):

```bash
cd <this-repo>
python3 -m venv venv
./venv/bin/pip install -e .
```

This installs only `aiohttp`, `cryptography`, `zeroconf`, `pyyaml`, and `aiomqtt`
(no Home Assistant) and puts a `sonoff-collector` command in `venv/bin`. Because
`standalone/` is self-contained you can also build a wheel (`python -m build`) and
`pip install` it anywhere.

## 1. One-time setup (interactive)

```bash
cp config.example.yaml config.yaml      # edit paths/log level as desired
./venv/bin/sonoff-collector login --config config.yaml
```

You'll be prompted for your eWeLink username, password (hidden), and country
code, then asked which home(s) to collect. On success it writes two
**`chmod 600`** files next to your config:

- `devices.json` — the device cache (contains `devicekey`s — keep it private);
- `credentials.yaml` — `{ username, token, homes }`. The token lets you re-sync
  later without re-entering your password:

```bash
./venv/bin/sonoff-collector login --refresh --config config.yaml
```

If the stored token has expired, `--refresh` falls back to the interactive
prompt. The **service never reads** `credentials.yaml`.

## 2. Run the collector

```bash
./venv/bin/sonoff-collector run --config config.yaml
```

It discovers devices over mDNS and logs each update, e.g.:

```
INFO  ewelink.local | 100abc1234 <= Local3 | 192.168.1.50:8081 | ...
INFO  standalone.registry | UPDATE 100abc1234 (Kitchen Plug) <= {'switch': 'on', 'power': 12.3}
```

(`python -m standalone run --config config.yaml` works too, if you prefer.)

## 3. Forward to MQTT / Home Assistant

Configure the broker once (stored **chmod 600** in `mqtt.yaml`, never in
`config.yaml`):

```bash
./venv/bin/sonoff-collector mqtt-login --config config.yaml
```

With `mqtt.yaml` present, `run` publishes using **HA MQTT Discovery**, so each
device shows up in Home Assistant automatically:

- **State** (retained): `sonoff/<deviceid>/state` — full params as JSON.
- **Discovery** (retained): `homeassistant/<component>/sonoff_<deviceid>/<param>/config`.
- **Availability** (LWT): `sonoff/status` = `online`/`offline`.
- **Control:** `switch` becomes a controllable HA entity. HA publishes to
  `sonoff/<deviceid>/set/switch`; the collector calls the core's `registry.send()`
  → the device over the **LAN** (no cloud). Commands for a device not yet
  discovered on the LAN are logged and dropped.

Known params get proper device classes/units (temperature, humidity, power,
voltage, current, rssi, battery); `switch` is controllable; every other scalar
param becomes a generic sensor — so all collected data appears.

### Test it without devices

No LAN devices yet? Replay jittered values from your real `devices.json`:

```bash
./venv/bin/sonoff-collector simulate --config config.yaml --interval 5
```

Watch them (and the discovery configs) arrive:

```bash
mosquitto_sub -h <broker> -u <user> -P <pass> -t 'homeassistant/#' -t 'sonoff/#' -v
```

The simulated device + entities should appear in Home Assistant and update every
interval. (Actuating the HA switch needs the real devices on your LAN.)

## 4. Install as a systemd service

Edit paths/user in [`systemd/sonoff-collector.service`](systemd/sonoff-collector.service),
then:

```bash
sudo useradd --system --no-create-home sonoff      # or reuse an existing user
sudo mkdir -p /etc/sonoff-collector
sudo cp config.yaml devices.json credentials.yaml mqtt.yaml /etc/sonoff-collector/
sudo chown -R sonoff:sonoff /etc/sonoff-collector
sudo cp systemd/sonoff-collector.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sonoff-collector
journalctl -u sonoff-collector -f
```

`systemctl stop` shuts the collector down cleanly; `Restart=on-failure` restarts
it if the process dies.

> **mDNS note:** discovery needs LAN multicast. Run on the host network (the
> default for a systemd service). The unit ships with some `Protect*` hardening
> — relax it if it interferes on your system.

## Caveats

- **Local-only:** only LAN-reachable devices report. A purely cloud-only device
  (some battery / Zigbee-bridged models without a LAN endpoint) won't appear.
- **Refreshing devices:** after adding/removing devices in the eWeLink app,
  re-run `login --refresh` (or `login`) to update `devices.json`.
- **Secrets at rest:** `devices.json` (devicekeys), `credentials.yaml` (eWeLink
  token), and `mqtt.yaml` (broker password) are all written `chmod 600`; keep them
  that way. Set `tls: true` in `mqtt.yaml` so the broker password isn't sent in the
  clear.

## How it stays Home-Assistant-free

The Home-Assistant-free transport core (`ewelink`: `XRegistry` + the cloud/local
transports) is **vendored** into `standalone/ewelink/` — a byte-identical copy of
`custom_components/sonoff/core/ewelink/` (minus `camera.py`; see
`standalone/ewelink/VENDORED.md`). It pulls in only `aiohttp`/`cryptography`/
`zeroconf`, never Home Assistant. The only HA imports it *could* reach are lazy
`from ..devices import …` calls inside two `XRegistry` methods, both overridden in
`standalone/registry.py`, so they never run. `custom_components/` is not imported
at runtime and is left unmodified.
