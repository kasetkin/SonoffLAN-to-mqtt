"""The ``run`` service: local-only collection. Never contacts the eWeLink cloud."""

import asyncio
import logging
import signal

import aiohttp
from zeroconf.asyncio import AsyncZeroconf

from .auth import load_devices
from .registry import StandaloneRegistry

_LOGGER = logging.getLogger(__name__)

USER_AGENT = "SonoffLAN-standalone/0.1"


async def run(config) -> int:
    devices = load_devices(config.devices_file)
    if not devices:
        _LOGGER.error(
            "No device cache at %s — run `sonoff-collector login` first.",
            config.devices_file,
        )
        return 2

    session = aiohttp.ClientSession(headers={"User-Agent": USER_AGENT})
    registry = StandaloneRegistry(session, devicekeys=config.devicekeys)
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
        # local discovery + LAN poll loop only; no cloud login, no WebSocket
        registry.local.start(aiozc.zeroconf)
        _LOGGER.info("Local mode started; discovering devices over mDNS…")
        await asyncio.sleep(3)
        _LOGGER.info("Collector running (local-only). Send SIGTERM/Ctrl-C to stop.")
        await stop.wait()
    finally:
        _LOGGER.info("Shutting down…")
        await registry.stop()
        await aiozc.async_close()
        await session.close()

    return 0
