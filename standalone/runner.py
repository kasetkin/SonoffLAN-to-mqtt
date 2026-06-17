"""The ``run`` service: local-only collection, optionally bridged to MQTT.

Never contacts the eWeLink cloud. With an `mqtt.yaml` present it forwards device
state to MQTT (HA discovery) and accepts commands back, sending them to devices
over the LAN via `registry.send()`.
"""

import asyncio
import logging
import signal

import aiohttp
from zeroconf.asyncio import AsyncZeroconf

from .auth import load_devices
from .mqtt import MqttConfig, MqttForwarder
from .registry import StandaloneRegistry

_LOGGER = logging.getLogger(__name__)

USER_AGENT = "SonoffLAN-standalone/0.1"


def make_command_handler(registry):
    """Build the async MQTT-command handler: HA → device over the LAN (no cloud)."""

    async def handle(deviceid: str, param: str, payload: str) -> None:
        device = registry.devices.get(deviceid)
        if not device:
            _LOGGER.warning("command for unknown device %s; dropped", deviceid)
            return
        if not (registry.can_local(device) or registry.can_cloud(device)):
            _LOGGER.warning(
                "device %s not reachable (not discovered on LAN yet); command dropped",
                deviceid,
            )
            return
        await registry.send(device, {param: payload})

    return handle


async def run(config) -> int:
    devices = load_devices(config.devices_file)
    if not devices:
        _LOGGER.error(
            "No device cache at %s — run `sonoff-collector login` first.",
            config.devices_file,
        )
        return 2

    mqtt_cfg = MqttConfig.load(config.mqtt_file)
    session = aiohttp.ClientSession(headers={"User-Agent": USER_AGENT})

    forwarder = MqttForwarder(mqtt_cfg) if mqtt_cfg else None
    registry = StandaloneRegistry(
        session,
        devicekeys=config.devicekeys,
        on_update=(forwarder.handle if forwarder else None),
    )
    if forwarder:
        forwarder.on_command = make_command_handler(registry)

    aiozc = AsyncZeroconf()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass  # not supported on some platforms (e.g. Windows)

    try:
        registry.setup_devices(devices)
        if forwarder:
            forwarder.start()
            _LOGGER.info("MQTT forwarding enabled → %s:%s", mqtt_cfg.host, mqtt_cfg.port)
        else:
            _LOGGER.info("No MQTT config at %s; logging updates only", config.mqtt_file)
        # local discovery + LAN poll loop only; no cloud login, no WebSocket
        registry.local.start(aiozc.zeroconf)
        _LOGGER.info("Local mode started; discovering devices over mDNS…")
        await asyncio.sleep(3)
        _LOGGER.info("Collector running (local-only). Send SIGTERM/Ctrl-C to stop.")
        await stop.wait()
    finally:
        _LOGGER.info("Shutting down…")
        await registry.stop()
        if forwarder:
            await forwarder.close()
        await aiozc.async_close()
        await session.close()

    return 0
