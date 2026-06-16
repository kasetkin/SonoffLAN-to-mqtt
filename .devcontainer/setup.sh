#!/bin/bash
set -e

# Allow git to operate in bind-mounted workspace (owned by host UID, not container UID)
git config --global --add safe.directory '*'
