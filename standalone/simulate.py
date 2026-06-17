"""``simulate``: replay jittered params from ``devices.json`` through the real
``registry._on_update`` → MQTT publish path, to test forwarding without LAN
devices. Requires a configured broker (``mqtt-login``).
"""

import asyncio
import logging
import random
import signal

import aiohttp

from .auth import load_devices
from .mqtt import MqttConfig, MqttForwarder
from .registry import StandaloneRegistry
from .runner import make_command_handler

_LOGGER = logging.getLogger(__name__)


def _jitter(params: dict) -> dict:
    """Produce a plausible delta: jitter numbers, occasionally toggle on/off."""
    delta: dict = {}
    for k, v in params.items():
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            delta[k] = round(v + random.uniform(-1.5, 1.5), 2)
        elif isinstance(v, str):
            if v in ("on", "off"):
                if random.random() < 0.3:
                    delta[k] = "off" if v == "on" else "on"
            else:
                try:
                    delta[k] = str(round(float(v) + random.uniform(-0.5, 0.5), 1))
                except ValueError:
                    pass  # leave non-numeric strings unchanged
    return delta


async def simulate(config, interval: float) -> int:
    devices = load_devices(config.devices_file)
    if not devices:
        _LOGGER.error(
            "No device cache at %s — run `sonoff-collector login` first.",
            config.devices_file,
        )
        return 2

    mqtt_cfg = MqttConfig.load(config.mqtt_file)
    if not mqtt_cfg:
        _LOGGER.error(
            "No MQTT config at %s — run `sonoff-collector mqtt-login` first.",
            config.mqtt_file,
        )
        return 2

    session = aiohttp.ClientSession()
    forwarder = MqttForwarder(mqtt_cfg)
    registry = StandaloneRegistry(
        session, devicekeys=config.devicekeys, on_update=forwarder.handle
    )
    forwarder.on_command = make_command_handler(registry)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    registry.setup_devices(devices)
    forwarder.start()
    _LOGGER.info(
        "Simulating %d device(s) → %s:%s every %.1fs. Ctrl-C to stop.",
        len(registry.devices),
        mqtt_cfg.host,
        mqtt_cfg.port,
        interval,
    )

    try:
        await asyncio.sleep(1)  # let the client connect + publish discovery
        while not stop.is_set():
            for did, device in list(registry.devices.items()):
                delta = _jitter(device.get("params") or {})
                if delta:
                    device["params"].update(delta)
                    registry._on_update(did, delta)
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass
    finally:
        _LOGGER.info("Shutting down…")
        await forwarder.close()
        await session.close()

    return 0
