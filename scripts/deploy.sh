#!/usr/bin/env bash
# Install the stand-alone Sonoff collector from this source bundle (install-only).
# Run this ON THE SERVER, inside the extracted bundle directory:
#     tar xzf sonoff-collector-<ver>.tar.gz && cd sonoff-collector-<ver> && ./deploy.sh
#
# It creates a venv, installs the collector, and scaffolds config.yaml. The
# interactive login / mqtt-login and the (optional) systemd setup are printed at
# the end for you to run.
set -euo pipefail

cd "$(dirname "$0")"
HERE="$PWD"

echo "==> Creating virtualenv at $HERE/venv"
if ! python3 -m venv venv; then
    echo "ERROR: could not create a virtualenv. On Debian/Ubuntu install it first:" >&2
    echo "    sudo apt update && sudo apt install -y python3-venv" >&2
    exit 1
fi

./venv/bin/pip install --quiet --upgrade pip
echo "==> Installing the collector (pip install .)"
if ! ./venv/bin/pip install .; then   # use 'pip install -e .' to tweak the source in place
    cat >&2 <<'EOF'

ERROR: dependency install failed. On platforms without prebuilt wheels (32-bit ARM /
Raspberry Pi, or a brand-new Python) 'cffi' (for 'cryptography') has to be compiled.
Install the build prerequisites, then re-run this script:

    sudo apt update && sudo apt install -y python3-dev libffi-dev build-essential pkg-config
    rm -rf venv && ./deploy.sh
EOF
    exit 1
fi

if [ ! -f config.yaml ]; then
    cp config.example.yaml config.yaml
    echo "==> Scaffolded config.yaml"
fi

BIN="$HERE/venv/bin/sonoff-collector"
CFG="$HERE/config.yaml"
cat <<EOF

Done. Remaining steps (interactive — run them yourself):

  1) one-time eWeLink login (needs internet) -> writes devices.json + credentials.yaml
       $BIN login --config $CFG

  2) MQTT broker credentials -> writes mqtt.yaml (chmod 600)
       $BIN mqtt-login --config $CFG

  3) test in the foreground (Ctrl-C to stop); watch for 'Local3 | <ip>',
     a real 'UPDATE ... (THR316D)', and 'MQTT connected'
       $BIN run --config $CFG

  4) (optional) run as a systemd service — edit the unit's paths/User first so
     WorkingDirectory + ExecStart point at $HERE :
       sudoedit systemd/sonoff-collector.service
       sudo cp systemd/sonoff-collector.service /etc/systemd/system/
       sudo systemctl daemon-reload
       sudo systemctl enable --now sonoff-collector
       journalctl -u sonoff-collector -f
EOF
