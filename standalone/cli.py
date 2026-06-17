"""Command-line entry point: ``sonoff-collector {login,mqtt-login,run,simulate}``."""

import argparse
import asyncio
import logging
import sys

from .config import Config


def _setup_logging(level: str) -> None:
    lvl = getattr(logging, level, logging.INFO)
    logging.basicConfig(
        level=lvl,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    )
    # the reused transport core logs under the top-level "ewelink" logger
    logging.getLogger("ewelink").setLevel(lvl)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="sonoff-collector",
        description="Local-only collector for Sonoff/eWeLink LAN devices.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--config", help="path to config.yaml (default: built-in defaults)"
    )

    p_login = sub.add_parser(
        "login", parents=[common], help="interactive eWeLink login + device sync"
    )
    p_login.add_argument(
        "--refresh",
        action="store_true",
        help="re-sync the device list using the saved token (no prompt)",
    )
    sub.add_parser(
        "mqtt-login", parents=[common], help="configure the MQTT broker (chmod 600)"
    )
    sub.add_parser("run", parents=[common], help="run the local-only collector")
    p_sim = sub.add_parser(
        "simulate",
        parents=[common],
        help="publish fake data to MQTT (test without devices)",
    )
    p_sim.add_argument(
        "--interval", type=float, default=5.0, help="seconds between fake updates"
    )

    args = parser.parse_args(argv)
    config = Config.load(args.config)
    _setup_logging(config.log_level)

    if args.command == "login":
        from . import auth

        return asyncio.run(auth.login(config, refresh=args.refresh))

    if args.command == "mqtt-login":
        from . import mqtt

        return mqtt.mqtt_login(config)

    if args.command == "run":
        from . import runner

        return asyncio.run(runner.run(config))

    if args.command == "simulate":
        from . import simulate

        return asyncio.run(simulate.simulate(config, args.interval))

    return 1  # unreachable (subcommand is required)


if __name__ == "__main__":
    sys.exit(main())
