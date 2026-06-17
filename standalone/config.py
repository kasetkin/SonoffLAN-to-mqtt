"""Non-secret runtime configuration (a small YAML file).

Secrets (the eWeLink token, device keys, MQTT broker password) live in the
chmod-600 files referenced here, not in this config.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_LOGGER = logging.getLogger(__name__)

DEFAULT_DEVICES_FILE = "devices.json"
DEFAULT_CREDENTIALS_FILE = "credentials.yaml"
DEFAULT_MQTT_FILE = "mqtt.yaml"


@dataclass
class Config:
    devices_file: Path = Path(DEFAULT_DEVICES_FILE)
    credentials_file: Path = Path(DEFAULT_CREDENTIALS_FILE)
    mqtt_file: Path = Path(DEFAULT_MQTT_FILE)
    country_code: str = "+1"
    log_level: str = "INFO"
    # optional manual deviceid -> devicekey overrides (for DIY/local-only devices)
    devicekeys: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | None) -> "Config":
        data: dict = {}
        base = Path.cwd()

        if path:
            p = Path(path).expanduser()
            base = p.parent
            if p.is_file():
                data = yaml.safe_load(p.read_text()) or {}
            else:
                _LOGGER.warning("Config %s not found; using defaults", p)

        def _resolve(value: str) -> Path:
            fp = Path(value).expanduser()
            return fp if fp.is_absolute() else base / fp

        return cls(
            devices_file=_resolve(data.get("devices_file", DEFAULT_DEVICES_FILE)),
            credentials_file=_resolve(
                data.get("credentials_file", DEFAULT_CREDENTIALS_FILE)
            ),
            mqtt_file=_resolve(data.get("mqtt_file", DEFAULT_MQTT_FILE)),
            country_code=str(data.get("country_code", "+1")),
            log_level=str(data.get("log_level", "INFO")).upper(),
            devicekeys=dict(data.get("devicekeys") or {}),
        )
