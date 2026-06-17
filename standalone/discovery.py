"""Map Sonoff device params to Home Assistant MQTT Discovery configs.

Standalone (no Home Assistant import); mirrors a small, generic subset of the
integration's sensor/switch semantics. Every *scalar* param becomes an entity so
"forward all collected data" holds: known params get a proper device_class/unit,
``switch`` becomes a controllable switch, other on/off params become read-only
binary_sensors, and anything else becomes a generic sensor. Nested params
(dict/list) are skipped from discovery but remain in the state JSON.
"""

import re

# param -> (device_class, unit) for typed numeric sensors
SENSORS = {
    "temperature": ("temperature", "°C"),
    "currentTemperature": ("temperature", "°C"),
    "humidity": ("humidity", "%"),
    "currentHumidity": ("humidity", "%"),
    "power": ("power", "W"),
    "voltage": ("voltage", "V"),
    "current": ("current", "A"),
    "rssi": ("signal_strength", "dBm"),
    "battery": ("battery", "%"),
}

# params published as controllable switches (HA can command them back)
CONTROLLABLE = {"switch"}

_ON_OFF = {"on", "off"}


def _pretty(key: str) -> str:
    """currentTemperature -> 'Current Temperature'."""
    s = re.sub(r"(?<!^)(?=[A-Z])", " ", key)
    return s[:1].upper() + s[1:]


def state_topic(base: str, deviceid: str) -> str:
    return f"{base}/{deviceid}/state"


def availability_topic(base: str) -> str:
    return f"{base}/status"


def command_topic(base: str, deviceid: str, param: str) -> str:
    return f"{base}/{deviceid}/set/{param}"


def _device_block(device: dict) -> dict:
    deviceid = device["deviceid"]
    params = device.get("params") or {}
    block = {
        "identifiers": [f"sonoff_{deviceid}"],
        "name": device.get("name") or deviceid,
        "manufacturer": device.get("brandName"),
        "model": device.get("productModel"),
        "sw_version": params.get("fwVersion"),
    }
    return {k: v for k, v in block.items() if v is not None}


def _is_scalar(value) -> bool:
    return isinstance(value, (str, int, float)) and not isinstance(value, bool)


def _entity(key: str, value, base: str, deviceid: str):
    """Return (component, partial_config) or (None, None) to skip."""
    if not _is_scalar(value):
        return None, None

    tmpl = f"{{{{ value_json['{key}'] }}}}"
    cfg = {"name": _pretty(key), "value_template": tmpl}

    if key in CONTROLLABLE and value in _ON_OFF:
        cfg.update(
            {
                "command_topic": command_topic(base, deviceid, key),
                "payload_on": "on",
                "payload_off": "off",
                "state_on": "on",
                "state_off": "off",
            }
        )
        return "switch", cfg

    if value in _ON_OFF:
        cfg.update({"payload_on": "on", "payload_off": "off"})
        return "binary_sensor", cfg

    if key in SENSORS:
        device_class, unit = SENSORS[key]
        cfg.update(
            {
                "device_class": device_class,
                "unit_of_measurement": unit,
                "state_class": "measurement",
            }
        )
        return "sensor", cfg

    # any other scalar -> generic sensor (numeric gets a measurement state_class)
    if isinstance(value, (int, float)):
        cfg["state_class"] = "measurement"
    return "sensor", cfg


def build_entities(device: dict, base: str, prefix: str) -> list[tuple[str, dict]]:
    """Return [(config_topic, config_payload), ...] for one device."""
    deviceid = device["deviceid"]
    params = device.get("params") or {}
    dev_block = _device_block(device)
    st = state_topic(base, deviceid)
    avail = availability_topic(base)

    out: list[tuple[str, dict]] = []
    for key, value in params.items():
        component, cfg = _entity(key, value, base, deviceid)
        if component is None:
            continue
        cfg.update(
            {
                "state_topic": st,
                "availability_topic": avail,
                "unique_id": f"sonoff_{deviceid}_{key}",
                "object_id": f"sonoff_{deviceid}_{key}",
                "device": dev_block,
            }
        )
        config_topic = f"{prefix}/{component}/sonoff_{deviceid}/{key}/config"
        out.append((config_topic, cfg))
    return out
