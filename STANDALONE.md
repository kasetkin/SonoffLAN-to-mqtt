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

> Forwarding the collected data to MQTT is a planned next step. Today the
> service logs every update; the hook for publishing lives in
> `StandaloneRegistry._on_update` (`standalone/registry.py`).

## Requirements

- Python 3.10+
- Run on a host with **LAN multicast/mDNS** access to your Sonoff devices
  (same L2 network). The device firmware must expose its LAN interface
  (the eWeLink app's "LAN mode" / "Local control" enabled).

## Install

```bash
git clone https://github.com/AlexxIT/SonoffLAN.git /opt/sonoff-collector
cd /opt/sonoff-collector
python3 -m venv venv
./venv/bin/pip install -e .
```

This installs only `aiohttp`, `cryptography`, `zeroconf`, and `pyyaml` (no Home
Assistant) and puts a `sonoff-collector` command in `venv/bin`.

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

## 3. Install as a systemd service

Edit paths/user in [`systemd/sonoff-collector.service`](systemd/sonoff-collector.service),
then:

```bash
sudo useradd --system --no-create-home sonoff      # or reuse an existing user
sudo mkdir -p /etc/sonoff-collector
sudo cp config.yaml devices.json credentials.yaml /etc/sonoff-collector/
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
- **Secrets at rest:** `devices.json` holds `devicekey`s and `credentials.yaml`
  holds your access token — both are written `chmod 600`; keep them that way.

## How it stays Home-Assistant-free

`standalone/_core.py` puts `custom_components/sonoff/core` on `sys.path` and
imports `ewelink` as a top-level package. Because `core/` is a namespace package
(no `__init__.py`), this does **not** execute the HA-coupled
`custom_components/sonoff/__init__.py`. The only HA imports reachable from the
core are lazy calls inside two `XRegistry` methods, both overridden in
`standalone/registry.py`. Nothing under `custom_components/` is modified.
