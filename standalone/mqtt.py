"""MQTT broker config, interactive ``mqtt-login``, and the two-way forwarder.

The forwarder publishes HA MQTT-Discovery configs + device state, and subscribes
to command topics (``<base>/<deviceid>/set/<param>``) which it hands to an async
``on_command`` callback. Broker creds live in a chmod-600 ``mqtt.yaml`` written by
``mqtt-login`` (never in config.yaml).
"""

import asyncio
import dataclasses
import getpass
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from . import discovery

_LOGGER = logging.getLogger(__name__)


@dataclass
class MqttConfig:
    host: str
    port: int = 1883
    username: str | None = None
    password: str | None = None
    tls: bool = False
    base_topic: str = "sonoff"
    discovery_prefix: str = "homeassistant"
    qos: int = 0
    retain: bool = True
    client_id: str = "sonoff-collector"

    @classmethod
    def load(cls, path: Path) -> "MqttConfig | None":
        path = Path(path)
        if not path.is_file():
            return None
        data = yaml.safe_load(path.read_text()) or {}
        if "host" not in data:
            _LOGGER.warning("%s has no 'host'; MQTT disabled", path)
            return None
        names = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})


def save_mqtt(path: Path, cfg: MqttConfig) -> None:
    from .auth import _write_secret  # reuse the chmod-600 writer

    _write_secret(path, yaml.safe_dump(dataclasses.asdict(cfg), sort_keys=False))
    _LOGGER.info("Saved MQTT settings to %s (chmod 600)", path)


def mqtt_login(config) -> int:
    """Interactive: prompt for broker settings and store them chmod-600."""
    print("Configure the MQTT broker connection (stored chmod 600):")
    host = input("Broker host: ").strip()
    if not host:
        print("Host is required.")
        return 1
    port = input("Port [1883]: ").strip() or "1883"
    username = input("Username (blank for none): ").strip() or None
    password = getpass.getpass("Password (blank for none): ") or None
    tls = input("Use TLS? [y/N]: ").strip().lower().startswith("y")
    base = input("Base topic [sonoff]: ").strip() or "sonoff"
    prefix = input("HA discovery prefix [homeassistant]: ").strip() or "homeassistant"

    cfg = MqttConfig(
        host=host,
        port=int(port),
        username=username,
        password=password,
        tls=tls,
        base_topic=base,
        discovery_prefix=prefix,
    )
    save_mqtt(config.mqtt_file, cfg)
    print(
        f"\nSaved to {config.mqtt_file}. Test it without devices:\n"
        f"  sonoff-collector simulate --config <your-config.yaml>\n"
    )
    return 0


class MqttForwarder:
    """Publishes discovery + state and routes commands. One reconnecting client."""

    def __init__(self, cfg: MqttConfig, on_command=None):
        self.cfg = cfg
        self.on_command = on_command  # async (deviceid, param, payload) -> None
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=2000)
        self._task: asyncio.Task | None = None
        self._client = None
        self._closing = False
        self._announced: set[str] = set()  # deviceids with discovery sent this connection
        self._avail = discovery.availability_topic(cfg.base_topic)

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def close(self) -> None:
        self._closing = True
        # best-effort graceful "offline" (LWT only fires on unclean disconnect)
        if self._client is not None:
            try:
                await self._client.publish(self._avail, "offline", retain=True)
            except Exception:
                pass
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    # ---- publish side (called synchronously from registry._on_update) ----

    def handle(self, device: dict, params: dict) -> None:
        try:
            deviceid = device["deviceid"]
            if deviceid not in self._announced:
                self._announced.add(deviceid)
                for topic, payload in discovery.build_entities(
                    device, self.cfg.base_topic, self.cfg.discovery_prefix
                ):
                    self._enqueue(topic, json.dumps(payload), retain=True)
            st = discovery.state_topic(self.cfg.base_topic, deviceid)
            self._enqueue(
                st, json.dumps(device.get("params") or {}), retain=self.cfg.retain
            )
        except Exception as e:
            _LOGGER.warning("mqtt handle error", exc_info=e)

    def _enqueue(self, topic: str, payload: str, retain: bool) -> None:
        item = (topic, payload, retain)
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            try:  # drop oldest, keep memory bounded
                self._queue.get_nowait()
                self._queue.put_nowait(item)
            except Exception:
                pass

    # ---- connection / loops ----

    async def _run(self) -> None:
        import aiomqtt

        backoff = 1
        while not self._closing:
            try:
                tls_params = aiomqtt.TLSParameters() if self.cfg.tls else None
                async with aiomqtt.Client(
                    hostname=self.cfg.host,
                    port=self.cfg.port,
                    username=self.cfg.username,
                    password=self.cfg.password,
                    tls_params=tls_params,
                    identifier=self.cfg.client_id,
                    will=aiomqtt.Will(
                        self._avail, "offline", qos=self.cfg.qos, retain=True
                    ),
                ) as client:
                    self._client = client
                    backoff = 1
                    self._announced.clear()  # re-announce discovery on each connect
                    await client.publish(
                        self._avail, "online", qos=self.cfg.qos, retain=True
                    )
                    await client.subscribe(
                        f"{self.cfg.base_topic}/+/set/#", qos=self.cfg.qos
                    )
                    _LOGGER.info(
                        "MQTT connected to %s:%s", self.cfg.host, self.cfg.port
                    )
                    await self._serve(client)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                _LOGGER.warning("MQTT connection lost: %s", e)
            finally:
                self._client = None
            if not self._closing:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def _serve(self, client) -> None:
        """Run publish + command loops until one fails, then propagate."""
        pub = asyncio.create_task(self._publish_loop(client))
        cmd = asyncio.create_task(self._command_loop(client))
        try:
            await asyncio.wait({pub, cmd}, return_when=asyncio.FIRST_EXCEPTION)
        finally:
            for t in (pub, cmd):
                t.cancel()
            await asyncio.gather(pub, cmd, return_exceptions=True)
        for t in (pub, cmd):
            if not t.cancelled() and t.exception():
                raise t.exception()

    async def _publish_loop(self, client) -> None:
        while True:
            topic, payload, retain = await self._queue.get()
            await client.publish(topic, payload, qos=self.cfg.qos, retain=retain)

    async def _command_loop(self, client) -> None:
        async for message in client.messages:
            try:
                await self._dispatch(message)
            except Exception as e:
                _LOGGER.warning("command handling error", exc_info=e)

    async def _dispatch(self, message) -> None:
        parts = str(message.topic).split("/")
        if "set" not in parts:
            return
        i = parts.index("set")
        if i == 0 or i + 1 >= len(parts):
            return
        deviceid, param = parts[i - 1], parts[i + 1]
        payload = message.payload
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode()
        _LOGGER.info("CMD %s %s <= %s", deviceid, param, payload)
        if self.on_command:
            await self.on_command(deviceid, param, str(payload))
