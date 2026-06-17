"""``StandaloneRegistry`` — ``XRegistry`` without the Home Assistant entity layer.

Differences from the core registry:

* ``setup_devices`` registers devices but builds no HA entities (and therefore
  never imports the HA-coupled ``devices.py``).
* ``local_update`` pre-registers an unknown LAN (DIY) device using a small local
  copy of the DIY table, so the core's lazy ``from ..devices import setup_diy``
  is never reached, then delegates to the core and forwards every update to an
  ``_on_update`` sink — the seam where MQTT publishing will plug in later.
"""

import logging

from ._core import XRegistry

_LOGGER = logging.getLogger(__name__)

# Mirror of custom_components/sonoff/core/devices.py DIY table + setup_diy
# (devices.py:854-888). Kept here so the standalone service never imports
# devices.py (which pulls in Home Assistant entity classes).
_DIY = {
    "plug": [1, None, "Single Channel DIY"],
    "strip": [4, None, "Multi Channel DIY"],
    "diy_plug": [1, "SONOFF", "MINI DIY"],
    "enhanced_plug": [5, "SONOFF", "POW DIY"],
    "th_plug": [15, "SONOFF", "TH DIY"],
    "rf": [28, "SONOFF", "RFBridge DIY"],
    "fan_light": [34, "SONOFF", "iFan DIY"],
    "light": [44, "SONOFF", "D1 DIY"],
    "diylight": [44, "SONOFF", "D1 DIY"],
    "diy_light": [136, "SONOFF", "B0x-BL DIY"],
    "switch_radar": [77, "SONOFF", "Micro DIY"],
    "multifun_switch": [126, "SONOFF", "DualR3 DIY"],
}


def _setup_diy(device: dict) -> dict:
    ltype = device.get("localtype")
    try:
        uiid, brand, model = _DIY[ltype]
        if ltype == "diy_plug" and "switches" in device["params"]:
            uiid, model = 77, "MINI R3 DIY"
        device["name"] = model
        device["brandName"] = brand
        device["extra"] = {"uiid": uiid}
        device["productModel"] = model
    except Exception:
        device["name"] = "Unknown DIY"
        device["extra"] = {"uiid": 0}
        device["productModel"] = ltype
    return device


class StandaloneRegistry(XRegistry):
    def __init__(self, session, devicekeys: dict | None = None, on_update=None):
        super().__init__(session)
        # core reads self.config["devices"][deviceid] as a dict of overrides
        self.config = {
            "devices": {
                did: {"devicekey": key} for did, key in (devicekeys or {}).items()
            }
        }
        self._sink = on_update

    def setup_devices(self, devices: list) -> list:
        # mirrors core setup_devices (ewelink/__init__.py:34-70) minus get_spec
        # and entity creation
        devices = sorted(
            devices, key=lambda d: d.get("params", {}).get("parentid", "")
        )
        for device in devices:
            did = device["deviceid"]
            try:
                device.update(self.config["devices"][did])
            except Exception:
                pass
            try:
                if parentid := device["params"].get("parentid"):
                    try:
                        device["parent"] = next(
                            d for d in devices if d["deviceid"] == parentid
                        )
                    except StopIteration:
                        pass
                self.devices[did] = device
                _LOGGER.debug(
                    "%s registered (uiid=%s)",
                    did,
                    device.get("extra", {}).get("uiid"),
                )
            except Exception as e:
                _LOGGER.warning("%s can't setup device", did, exc_info=e)
        _LOGGER.info("Registered %d device(s)", len(self.devices))
        return []

    def local_update(self, msg: dict):
        did = msg["deviceid"]

        # Pre-register an unknown LAN device locally so the core's HA-coupled
        # `from ..devices import setup_diy` branch is never taken.
        if did not in self.devices:
            params = msg.get("params")
            if not params:
                key = self.config["devices"].get(did, {}).get("devicekey")
                if key:
                    try:
                        msg["params"] = params = self.local.decrypt_msg(msg, key)
                    except Exception:
                        params = None
            if params:
                _LOGGER.info("%s discovered as a local DIY device", did)
                self.devices[did] = _setup_diy(msg)
            # else: encrypted device without a key -> let the core skip it

        super().local_update(msg)

        if params := msg.get("params"):
            self._on_update(msg.get("subdevid", did), params)

    def _on_update(self, deviceid: str, params: dict):
        device = self.devices.get(deviceid)
        name = device.get("name", "?") if device else "?"
        _LOGGER.info("UPDATE %s (%s) <= %s", deviceid, name, params)
        # The sink receives the FULL device (identity + merged params) so the MQTT
        # forwarder has everything it needs for discovery + full-state publishing.
        if self._sink and device:
            try:
                self._sink(device, params)
            except Exception as e:
                _LOGGER.warning("update sink error", exc_info=e)
