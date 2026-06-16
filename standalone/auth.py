"""eWeLink cloud login + device download, and secret-file persistence.

This is the ONLY place that talks to the eWeLink cloud. It writes two
``chmod 600`` files:

* the device cache (``devices.json``) — incl. each device's ``devicekey``;
* the credentials file (``credentials.yaml``) — ``{username, token, homes}``;
  the token (``region:at``) lets ``login --refresh`` re-sync without a password.
"""

import getpass
import json
import logging
import os
from pathlib import Path

import aiohttp
import yaml

from ._core import REGIONS, AuthError, XRegistry

_LOGGER = logging.getLogger(__name__)


def _write_secret(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # open with 0600 from the start to avoid a world-readable window
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.chmod(path, 0o600)


def save_devices(path: Path, devices: list) -> None:
    _write_secret(path, json.dumps(devices, indent=2))
    _LOGGER.info("Saved %d device(s) to %s (chmod 600)", len(devices), path)


def load_devices(path: Path) -> list | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text())


def save_credentials(path: Path, username: str, token: str, homes: list) -> None:
    text = yaml.safe_dump(
        {"username": username, "token": token, "homes": homes or []},
        sort_keys=False,
    )
    _write_secret(path, text)
    _LOGGER.info("Saved credentials to %s (chmod 600)", path)


def load_credentials(path: Path) -> dict | None:
    if not path.is_file():
        return None
    return yaml.safe_load(path.read_text())


def _prompt_credentials(default_country: str) -> tuple[str, str, str]:
    username = input("eWeLink username (email or +phone): ").strip()
    password = getpass.getpass("Password: ")
    while True:
        cc = input(f"Country code [{default_country}]: ").strip() or default_country
        if cc in REGIONS:
            return username, password, cc
        print(f"  '{cc}' is not a known country code (e.g. +1, +44, +86). Try again.")


def _select_homes(homes: dict) -> list:
    """``homes``: ``{id: name}``. Returns selected ids ([] means all)."""
    if not homes:
        return []
    items = list(homes.items())
    print("Homes:")
    for i, (_id, name) in enumerate(items, 1):
        print(f"  [{i}] {name}")
    raw = input("Collect which? (comma-separated numbers, blank = all): ").strip()
    if not raw:
        return []
    chosen = []
    for tok in raw.split(","):
        tok = tok.strip()
        if tok.isdigit() and 1 <= int(tok) <= len(items):
            chosen.append(items[int(tok) - 1][0])
    return chosen


async def _fetch_and_store(cloud, config, username: str, homes: list) -> None:
    devices = await cloud.get_devices(homes or None)
    save_devices(config.devices_file, devices)
    save_credentials(config.credentials_file, username, cloud.token, homes)


async def login(config, refresh: bool = False) -> int:
    async with aiohttp.ClientSession() as session:
        cloud = XRegistry(session).cloud

        # 1. Token refresh (no prompt) if requested and possible.
        if refresh:
            creds = load_credentials(config.credentials_file)
            if not creds or not creds.get("token"):
                print("No saved credentials; run `sonoff-collector login` first.")
                return 2
            try:
                await cloud.login(username="token", password=creds["token"])
                await _fetch_and_store(
                    cloud, config, creds.get("username", ""), creds.get("homes", [])
                )
                print("Device list refreshed.")
                return 0
            except AuthError as e:
                print(f"Stored token rejected ({e}); please log in again.\n")
                # fall through to interactive login

        # 2. Interactive login.
        username, password, country = _prompt_credentials(config.country_code)
        try:
            await cloud.login(username, password, country)
        except AuthError as e:
            print(f"Login failed: {e}")
            return 1
        except Exception as e:  # network / unexpected
            _LOGGER.error("Login error", exc_info=e)
            return 1

        homes = _select_homes(await cloud.get_homes())
        await _fetch_and_store(cloud, config, username, homes)

        print(
            "\nSetup complete. The service runs local-only:\n"
            "  sonoff-collector run --config <your-config.yaml>\n"
            "Note: eWeLink tokens expire; if `login --refresh` later fails, "
            "just run `login` again.\n"
        )
        return 0
