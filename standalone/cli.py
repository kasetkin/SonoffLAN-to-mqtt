"""Command-line entry point: ``sonoff-collector {login,run}``."""

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
    sub.add_parser("run", parents=[common], help="run the local-only collector")

    args = parser.parse_args(argv)
    config = Config.load(args.config)
    _setup_logging(config.log_level)

    if args.command == "login":
        from . import auth

        return asyncio.run(auth.login(config, refresh=args.refresh))

    if args.command == "run":
        from . import runner

        return asyncio.run(runner.run(config))

    return 1  # unreachable (subcommand is required)


if __name__ == "__main__":
    sys.exit(main())
