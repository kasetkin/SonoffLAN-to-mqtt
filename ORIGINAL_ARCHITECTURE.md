# SonoffLAN — Architecture & Module Reference

> **Scope of this document.** This is a structural map of the existing
> **SonoffLAN** Home Assistant integration (v3.12.0), written as the reference
> for extending this fork (`SonoffLAN-to-mqtt`) to forward all data collected
> from local-network Sonoff devices to an external MQTT broker. It describes
> what each module does, why it exists, and how device data flows through the
> system. Section 7 ("MQTT integration hook points") is **forward-looking
> design guidance, not yet-implemented behavior**.

---

## 1. Overview

SonoffLAN is a Home Assistant **custom integration** (domain `sonoff`) that
controls and monitors [Sonoff / eWeLink](https://ewelink.cc/) smart devices.

- **`iot_class: local_push`** — devices push state changes to the integration in
  near-real-time (no polling), so Home Assistant reflects changes instantly.
- **Dual transport.** Every device can be reached two ways, and the integration
  uses whichever is available (configurable: `auto` / `cloud` / `local`):
  - **Cloud** — eWeLink REST API (login, device list) + a persistent WebSocket
    that streams state updates.
  - **Local (LAN)** — devices are discovered on the local network via mDNS
    (zeroconf) and controlled over HTTP on port `8081`; payloads for non-DIY
    devices are AES-128-CBC encrypted with the device's `devicekey`.
- Both transports converge on a single in-memory **`XRegistry`**, which holds
  device state and broadcasts updates through a lightweight **signal
  dispatcher**. Home Assistant entities subscribe to that dispatcher.

**This fork's goal:** tap the converged data stream inside `XRegistry` and
republish device parameters to an MQTT broker, in addition to the existing
Home Assistant entities.

Key facts (from [custom_components/sonoff/manifest.json](custom_components/sonoff/manifest.json)):

| Field | Value |
|---|---|
| Domain | `sonoff` |
| Version | `3.12.0` |
| Min Home Assistant | `2023.2.0` |
| HA dependencies | `http`, `zeroconf` |
| External Python deps | none (`requirements: []`) |
| Config | UI config flow (`config_flow: true`) |

---

## 2. High-level architecture

```
                       Sonoff / eWeLink devices
                        │                     │
        ┌───────────────┘                     └──────────────┐
        │ Cloud                                       Local  │
        ▼                                                    ▼
 eWeLink REST + WebSocket                      mDNS discovery + HTTP :8081
 core/ewelink/cloud.py                         core/ewelink/local.py
 (XRegistryCloud)                              (XRegistryLocal)
        │  SIGNAL_UPDATE                  SIGNAL_UPDATE  │
        └──────────────────┐        ┌────────────────────┘
                           ▼        ▼
                  ┌─────────────────────────────┐
                  │        XRegistry            │   core/ewelink/__init__.py
                  │  devices: dict[id, XDevice] │
                  │  cloud_update / local_update│
                  │  send() with LAN→Cloud      │
                  │        failover             │
                  └──────────────┬──────────────┘
                                 │ dispatcher_send(deviceid, params)
                                 ▼
                  ┌─────────────────────────────┐
                  │   XEntity subscribers       │   core/entity.py
                  │   internal_update→set_state │
                  └──────────────┬──────────────┘
                                 │ _async_write_ha_state()
                                 ▼
                          Home Assistant
                  (switch / light / sensor / …)

       ◄── proposed MQTT tap point: at XRegistry, see §7
```

The **dispatcher** (`dispatcher_connect` / `dispatcher_send` in
[core/ewelink/base.py](custom_components/sonoff/core/ewelink/base.py#L62-L72))
is the architectural backbone: a device update is broadcast on a signal whose
name is the device's `deviceid`, and every entity belonging to that device is a
subscriber.

---

## 3. Repository layout

| Path | Purpose |
|---|---|
| [custom_components/sonoff/](custom_components/sonoff/) | The integration package (all runtime code). |
| [tests/](tests/) | Pytest suite (entity, energy, climate, backward-compat, misc). |
| [README.md](README.md) | End-user installation & configuration guide. |
| [DEVICES.md](DEVICES.md) | List of supported Sonoff devices. |
| [hacs.json](hacs.json) | HACS (Home Assistant Community Store) metadata. |
| [LICENSE.md](LICENSE.md) | License. |
| `.github/` | CI workflows and issue templates. |
| `.devcontainer/` | VS Code dev-container config (this fork). |

Package internals:

| Path | Purpose |
|---|---|
| [custom_components/sonoff/__init__.py](custom_components/sonoff/__init__.py) | Integration entry point & lifecycle. |
| [custom_components/sonoff/config_flow.py](custom_components/sonoff/config_flow.py) | UI setup/options flows. |
| [custom_components/sonoff/manifest.json](custom_components/sonoff/manifest.json) | Integration metadata. |
| [custom_components/sonoff/services.yaml](custom_components/sonoff/services.yaml) | `send_command` service definition. |
| [custom_components/sonoff/system_health.py](custom_components/sonoff/system_health.py) | System Health panel + debug log endpoint. |
| [custom_components/sonoff/diagnostics.py](custom_components/sonoff/diagnostics.py) | Diagnostics export (with secret masking). |
| `*.py` platform files (13) | Home Assistant entity platforms (see §4). |
| [custom_components/sonoff/core/](custom_components/sonoff/core/) | Transport, registry, entity base, device specs. |
| [custom_components/sonoff/translations/](custom_components/sonoff/translations/) | UI strings, 20 languages. |

---

## 4. Module-by-module reference

### 4.1 Entry & configuration

**[__init__.py](custom_components/sonoff/__init__.py)** — integration lifecycle.
- `async_setup` ([:104](custom_components/sonoff/__init__.py#L104)) — YAML import,
  global config (appid/appsecret, default device class, custom sensors), starts
  the `XCameras` thread and System Health.
- `async_setup_entry` ([:182](custom_components/sonoff/__init__.py#L182)) — the
  main per-account bootstrap: authenticates to cloud, loads the device list
  (cloud → local cache fallback), builds entities via the registry, forwards
  setup to all `PLATFORMS`, and starts cloud and/or local connections.
- `PLATFORMS` ([:47](custom_components/sonoff/__init__.py#L47)) — the 13 entity
  platforms to load (sensor first, so bridge devices initialize before children).
- `async_update_options` / `async_unload_entry` ([:278](custom_components/sonoff/__init__.py#L278),
  [:282](custom_components/sonoff/__init__.py#L282)) — reload on options change; teardown.
- `internal_unique_devices` ([:293](custom_components/sonoff/__init__.py#L293)) —
  de-duplicates devices across multiple configured accounts.

**[config_flow.py](custom_components/sonoff/config_flow.py)** — UI configuration.
- `FlowHandler` ([:15](custom_components/sonoff/config_flow.py#L15)) — login
  (`async_step_user` [:25](custom_components/sonoff/config_flow.py#L25)) and
  re-auth (`async_step_reauth` [:88](custom_components/sonoff/config_flow.py#L88)).
- `OptionsFlowHandler` ([:98](custom_components/sonoff/config_flow.py#L98)) — mode
  (`auto`/`cloud`/`local`), debug, and home selection.

**[core/const.py](custom_components/sonoff/core/const.py)** — `DOMAIN`, the
`CONF_*` option keys, `CONF_MODES = ["auto", "cloud", "local"]`, and
`PRIVATE_KEYS` (params masked in diagnostics).

**[services.yaml](custom_components/sonoff/services.yaml)** — declares the
`send_command` service for sending raw parameter dicts to a device.

### 4.2 Communication core — [core/ewelink/](custom_components/sonoff/core/ewelink/)

**[base.py](custom_components/sonoff/core/ewelink/base.py)** — shared primitives.
- `XDevice` ([:11](custom_components/sonoff/core/ewelink/base.py#L11)) — the
  `TypedDict` describing a device (see §5).
- `XRegistryBase` ([:42](custom_components/sonoff/core/ewelink/base.py#L42)) — the
  dispatcher and sequence-number generator that both the registry and the two
  transports inherit:
  - `sequence` ([:51](custom_components/sonoff/core/ewelink/base.py#L51)) —
    monotonic, unique millisecond message IDs.
  - `dispatcher_connect` / `dispatcher_send` ([:62](custom_components/sonoff/core/ewelink/base.py#L62),
    [:68](custom_components/sonoff/core/ewelink/base.py#L68)) — subscribe/broadcast
    by signal name. `SIGNAL_CONNECTED` and `SIGNAL_UPDATE` are the transport-level
    signals; device-level signals are the raw `deviceid` strings.

**[__init__.py](custom_components/sonoff/core/ewelink/__init__.py)** — `XRegistry`
([:17](custom_components/sonoff/core/ewelink/__init__.py#L17)), the central
coordinator and the heart of the data flow.
- `devices: dict[str, XDevice]` ([:24](custom_components/sonoff/core/ewelink/__init__.py#L24)) —
  the in-memory device store, keyed by `deviceid`.
- Wires the two transports' `SIGNAL_UPDATE`/`SIGNAL_CONNECTED` to its own
  handlers ([:26-32](custom_components/sonoff/core/ewelink/__init__.py#L26-L32)).
- `setup_devices` ([:34](custom_components/sonoff/core/ewelink/__init__.py#L34)) —
  resolves parents, calls `get_spec(device)` to instantiate the right entity
  classes, and registers each device in `self.devices`.
- `send` ([:87](custom_components/sonoff/core/ewelink/__init__.py#L87)) — outbound
  command with **LAN-first, Cloud-fallback** logic (`can_local`/`can_cloud`).
- **`cloud_update` ([:214](custom_components/sonoff/core/ewelink/__init__.py#L214))**
  and **`local_update` ([:241](custom_components/sonoff/core/ewelink/__init__.py#L241))** —
  inbound update handlers; **this is where all device state converges** (see §6 & §7).
- `run_forever` ([:314](custom_components/sonoff/core/ewelink/__init__.py#L314)) —
  5-second loop refreshing local power/TH sensors and pinging for liveness.

**[cloud.py](custom_components/sonoff/core/ewelink/cloud.py)** — `XRegistryCloud`
([:300](custom_components/sonoff/core/ewelink/cloud.py#L300)), the cloud transport.
- Regional endpoints in `API` / `WS` ([:25](custom_components/sonoff/core/ewelink/cloud.py#L25),
  [:32](custom_components/sonoff/core/ewelink/cloud.py#L32)); app credentials `APP`
  ([:249](custom_components/sonoff/core/ewelink/cloud.py#L249)).
- `login` / `get_devices` ([:331](custom_components/sonoff/core/ewelink/cloud.py#L331),
  [:400](custom_components/sonoff/core/ewelink/cloud.py#L400)) — HMAC-SHA256-signed REST.
- `send` ([:435](custom_components/sonoff/core/ewelink/cloud.py#L435)) — `update`/`query`
  over WebSocket, with a `ResponseWaiter` ([:256](custom_components/sonoff/core/ewelink/cloud.py#L256))
  matching responses by sequence.
- `_process_ws_msg` ([:604](custom_components/sonoff/core/ewelink/cloud.py#L604)) —
  parses incoming WS frames and emits `SIGNAL_UPDATE`.

**[local.py](custom_components/sonoff/core/ewelink/local.py)** — `XRegistryLocal`
([:60](custom_components/sonoff/core/ewelink/local.py#L60)), the LAN transport.
- `_handler1/2/3` ([:77](custom_components/sonoff/core/ewelink/local.py#L77)–[:125](custom_components/sonoff/core/ewelink/local.py#L125)) —
  zeroconf discovery of `_ewelink._tcp.local.`, resolving host + TXT-record state,
  emitting `SIGNAL_UPDATE`.
- `encrypt` / `decrypt` / `decrypt_msg` ([:28](custom_components/sonoff/core/ewelink/local.py#L28),
  [:47](custom_components/sonoff/core/ewelink/local.py#L47),
  [:268](custom_components/sonoff/core/ewelink/local.py#L268)) — AES-128-CBC using
  `MD5(devicekey)`; DIY devices are unencrypted.
- `send` ([:148](custom_components/sonoff/core/ewelink/local.py#L148)) — HTTP POST to
  `http://{host}:8081/zeroconf/{command}`.

**[camera.py](custom_components/sonoff/core/ewelink/camera.py)** — `XCameras`
([:70](custom_components/sonoff/core/ewelink/camera.py#L70)), a background thread
for Sonoff GK-200MP2-B camera streaming. Set up directly in `async_setup`, **not**
a Home Assistant platform.

### 4.3 Entity framework

**[core/entity.py](custom_components/sonoff/core/entity.py)** — `XEntity`
([:38](custom_components/sonoff/core/entity.py#L38)), the base class for **every**
Sonoff entity across all platforms.
- `params: set` — the device-param keys this entity cares about (the update filter).
- On init: builds `unique_id`, name, and `DeviceInfo` (MAC, manufacturer, model,
  firmware, uiid), then **subscribes to the dispatcher** for its `deviceid`
  ([:93](custom_components/sonoff/core/entity.py#L93)).
- `internal_update` ([:115-128](custom_components/sonoff/core/entity.py#L115-L128)) —
  dispatcher callback; if the incoming params intersect `self.params`, calls
  `set_state(params)` and writes HA state.
- `set_state` ([:108](custom_components/sonoff/core/entity.py#L108)) — no-op base;
  **each subclass overrides it** to map raw params → HA state/attributes.

**[core/devices.py](custom_components/sonoff/core/devices.py)** — the device-type →
entity mapping (the integration's "device database").
- `DEVICES` ([:200](custom_components/sonoff/core/devices.py#L200)) — the big dict
  mapping each device **`uiid`** to the list of entity classes it produces.
- `spec()` ([:112](custom_components/sonoff/core/devices.py#L112)) — a factory that
  derives parameterized entity subclasses (e.g. `Switch1 = spec(XSwitches, channel=0)`),
  optionally swapping the base class (switch→light).
- `get_spec()` ([:749](custom_components/sonoff/core/devices.py#L749)) — picks the
  class list for a device (by `uiid`, with runtime tweaks for cover-mode DualR3,
  NSPanel without climate, battery-less SNZB-06P, custom `device_class`), and
  always appends `XConnection`.
- `setup_diy()` ([:871](custom_components/sonoff/core/devices.py#L871)) — synthesizes
  a device record for a locally-discovered DIY device not present in the cloud list.

### 4.4 Home Assistant platform files

Each platform file follows the same shape: an `async_setup_entry` that subscribes
to `SIGNAL_ADD_ENTITIES`, plus `XEntity` subclasses overriding `set_state`.

| Platform file | Handles (examples) | Representative entity classes |
|---|---|---|
| [switch.py](custom_components/sonoff/switch.py) | Relays, multi-channel, POWR3, LED/inching toggles | `XSwitch`, `XSwitches`, `XSwitchTH`, `XSwitchPOWR3`, `XToggle` |
| [light.py](custom_components/sonoff/light.py) | Bulbs, dimmers, RGB/CCT, strips, T5, fan light | `XLight`, `XDimmer`, `XLightB1/B02/D1/L1/L3`, `XZigbeeLight`, `XT5*` |
| [sensor.py](custom_components/sonoff/sensor.py) | Power/voltage/current, energy, temp/humidity, RSSI, battery, connection, buttons | `XSensor`, `XTemperatureTH`, `XHumidityTH`, `XCloudEnergy*`, `XConnection`, `XButtonKey` |
| [binary_sensor.py](custom_components/sonoff/binary_sensor.py) | Water, motion (PIR/Zigbee), door, light-detect, RF | `XBinarySensor`, `XWiFiDoor`, `XZigbeeMotion`, `XWaterSensor`, `XRemoteSensor` |
| [climate.py](custom_components/sonoff/climate.py) | TH thermostat, NSPanel, TRVZB | `XClimateTH`, `XClimateNS`, `XThermostat`, `XThermostatTRVZB` |
| [fan.py](custom_components/sonoff/fan.py) | iFan, DualR3 fan, diffuser fan | `XFan`, `XFan17`, `XFanDualR3`, `XDiffuserFan`, `XToggleFan` |
| [cover.py](custom_components/sonoff/cover.py) | Curtains/shades, DualR3 cover, T5, Zigbee | `XCover`, `XCoverOP`, `XCoverDualR3`, `XCoverT5`, `XZigbeeCover` |
| [number.py](custom_components/sonoff/number.py) | Inching duration, sensitivity, temp correction | `XNumber`, `XPulseWidth`, `XSensitivity`, `XTempCorrectionNumber` |
| [button.py](custom_components/sonoff/button.py) | RF-bridge buttons, T5 effects | `XButton`, `XRemoteButton`, `XT5Effect` |
| [select.py](custom_components/sonoff/select.py) | Power-on startup state | `XSelectStartup`, `XStartup` |
| [remote.py](custom_components/sonoff/remote.py) | RF Bridge 433 remotes | `XRemote` |
| [media_player.py](custom_components/sonoff/media_player.py) | NSPanel buzzer | `XPanelBuzzer` |
| [alarm_control_panel.py](custom_components/sonoff/alarm_control_panel.py) | Panel alarm states | `XPanelAlarm` |

### 4.5 Support & diagnostics

| File | Role |
|---|---|
| [system_health.py](custom_components/sonoff/system_health.py) | `system_health_info` ([:28](custom_components/sonoff/system_health.py#L28)) reports cloud/local online counts; `DebugView` ([:72](custom_components/sonoff/system_health.py#L72)) serves live integration logs over HTTP. |
| [diagnostics.py](custom_components/sonoff/diagnostics.py) | Config-entry & per-device diagnostics export, masking `PRIVATE_KEYS` (passwords, MAC, devicekeys). |
| [core/xutils.py](custom_components/sonoff/core/xutils.py) | `source_hash` (version fingerprint), `system_log_records`, `create_clientsession` (custom User-Agent HTTP session). |
| [translations/](custom_components/sonoff/translations/) | 20 localized UI string files. |

### 4.6 Tests — [tests/](tests/)

| File | Covers |
|---|---|
| [tests/test_entity.py](tests/test_entity.py) | The bulk of entity behavior across platforms (largest suite). |
| [tests/test_energy.py](tests/test_energy.py) | Energy/power sensor decoding & history. |
| [tests/test_climate.py](tests/test_climate.py) | Thermostat / TRV / NSPanel climate logic. |
| [tests/test_backward.py](tests/test_backward.py) | Backward-compatibility guarantees. |
| [tests/test_misc.py](tests/test_misc.py) | Misc utilities. |
| [tests/pytest.ini](tests/pytest.ini) | Pytest configuration. |

---

## 5. Data model — `XDevice`

Defined as a `TypedDict` in
[core/ewelink/base.py:11](custom_components/sonoff/core/ewelink/base.py#L11). A
device is a plain dict; the most relevant fields:

| Field | Meaning |
|---|---|
| `deviceid` | 10-char unique ID; also the dispatcher signal name. |
| `name` | User-facing device name. |
| `extra.uiid` | Numeric model/type code that drives entity selection (`get_spec`). |
| `params` | **The live state dict** — e.g. `{"switch": "on", "power": 625, ...}`. This is the data of interest for MQTT. |
| `brandName`, `productModel` | Manufacturer/model strings for `DeviceInfo`. |
| `online`, `apikey` | Cloud reachability + key (required for cloud). |
| `local`, `host`, `localtype`, `devicekey` | LAN reachability, `ip:port`, discovery type, AES key. |
| `localrecv`, `localping`, `localfail` | LAN liveness bookkeeping (used by `run_forever`). |
| `cloud_seq`, `local_seq` | Last message sequence per transport. |
| `parent` | Reference to a bridge/parent device (RF bridge, SPM-Main, Zigbee bridge). |

**Example `params` for a Sonoff POW2 (uiid 32):**

```jsonc
{
  "switch": "on",
  "current": 2.5,            // A
  "power": 625.0,            // W
  "voltage": 230.0,          // V
  "hundredDaysKwhData": "…", // encoded energy history
  "rssi": -68,
  "fwVersion": "3.1.6",
  "staMac": "aa:bb:cc:dd:ee:ff"
}
```

---

## 6. Data flow walkthrough

The same merge-and-broadcast pattern applies to both transports.

**Cloud path**
1. WebSocket frame arrives → `XRegistryCloud._process_ws_msg`
   ([cloud.py:604](custom_components/sonoff/core/ewelink/cloud.py#L604)) emits
   `SIGNAL_UPDATE`.
2. `XRegistry.cloud_update`
   ([__init__.py:214](custom_components/sonoff/core/ewelink/__init__.py#L214))
   updates `online`/`cloud_seq` and broadcasts:
   **`dispatcher_send(did, params)`**
   ([:239](custom_components/sonoff/core/ewelink/__init__.py#L239)).

**Local path**
1. zeroconf / HTTP response → `XRegistryLocal` emits `SIGNAL_UPDATE`.
2. `XRegistry.local_update`
   ([__init__.py:241](custom_components/sonoff/core/ewelink/__init__.py#L241))
   decrypts if needed, **merges into `device["params"]`**
   ([:291-294](custom_components/sonoff/core/ewelink/__init__.py#L291-L294)),
   updates liveness, and broadcasts:
   **`dispatcher_send(realid, params)`**
   ([:308](custom_components/sonoff/core/ewelink/__init__.py#L308)). For
   sub-devices it also pings the parent with `None`
   ([:312](custom_components/sonoff/core/ewelink/__init__.py#L312)).

**Entity side (both paths)**
3. Each subscribed `XEntity.internal_update`
   ([entity.py:115-128](custom_components/sonoff/core/entity.py#L115-L128)) checks
   `params.keys() & self.params`; on a match it calls `set_state(params)` and
   `_async_write_ha_state()`.

> Note: `dispatcher_send(did)` is sometimes called with **no params** (e.g.
> `cloud_connected` [:203](custom_components/sonoff/core/ewelink/__init__.py#L203),
> `send_local` on/offline transitions) purely to refresh availability. Any new
> subscriber must tolerate `params=None`.

---

## 7. MQTT integration hook points *(proposal — not yet implemented)*

**Recommendation: tap `XRegistry`, not the entities.** Both transports converge
in `cloud_update` / `local_update` with the device's merged `params`, *before*
the per-entity `params` filter discards anything. The registry therefore sees
**every parameter of every device** in one place, transport-agnostic — exactly
what a "forward everything to MQTT" feature needs. Entities, by contrast, each
see only their own slice (`self.params`) and the data is already reshaped into
HA state.

**Context available at the tap point** (all from the `XDevice` in `self.devices`):
`deviceid`, `name`, `extra.uiid`, the full merged `device["params"]`, and the
cloud-vs-local origin (which handler fired). Enough to build, e.g.,
`sonoff/<deviceid>/state` topics with a JSON `params` payload.

Two concrete implementation options:

1. **Direct hook (most complete).** Add a forwarding call inside
   [cloud_update](custom_components/sonoff/core/ewelink/__init__.py#L214) and
   [local_update](custom_components/sonoff/core/ewelink/__init__.py#L241), right
   before each `dispatcher_send`. Pros: sees raw `params` and the exact origin;
   single chokepoint. Cons: edits two core methods.

2. **Extra dispatcher subscriber (least invasive).** In
   [setup_devices](custom_components/sonoff/core/ewelink/__init__.py#L34),
   alongside entity creation, register one more listener per device:
   `dispatcher_connect(deviceid, forwarder)`. The forwarder closes over the
   `deviceid` (the signal passes only `params`). Pros: no edits to the update
   handlers; rides the existing broadcast. Cons: must read `device["params"]`
   from the registry for full state, and must tolerate `params=None`
   availability pings (see §6 note).

Either way, the MQTT client lifecycle (connect/disconnect) fits naturally next
to the cloud/local connections in
[async_setup_entry](custom_components/sonoff/__init__.py#L182) /
[async_unload_entry](custom_components/sonoff/__init__.py#L282), with broker
settings added to the options flow in
[config_flow.py](custom_components/sonoff/config_flow.py).

> The detailed MQTT design (topic scheme, payload format, QoS/retain, broker
> config, reconnection) is intentionally out of scope here and will be its own
> plan. This section only fixes **where** to integrate.

---

## 8. Glossary

| Term | Meaning |
|---|---|
| **eWeLink** | The cloud platform / app behind Sonoff (CoolKit). |
| **UIID** | Numeric device-type code in `extra.uiid`; the key into `DEVICES` that determines which entities a device gets. |
| **DIY mode** | A device flashed/configured to expose an unencrypted LAN API; discovered locally without a cloud account, set up via `setup_diy`. |
| **LAN mode / local_push** | Local control over HTTP :8081 with mDNS discovery; "local_push" = devices push state without polling. |
| **apikey vs devicekey** | `apikey` authenticates cloud/WebSocket requests; `devicekey` is the per-device AES key for encrypted LAN payloads. |
| **dispatcher** | The in-process pub/sub in `XRegistryBase` (`dispatcher_connect`/`dispatcher_send`) that routes updates from the registry to entities by `deviceid`. |
| **`spec()` / derived classes** | Factory in `devices.py` that mints small `XEntity` subclasses with parameter overrides (channel, param name, base class) to avoid hand-writing each variant. |

---

*Generated as a structural reference for the planned MQTT-forwarding extension.
Line references are accurate to SonoffLAN v3.12.0 as of this commit.*
