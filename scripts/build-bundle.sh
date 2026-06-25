#!/usr/bin/env bash
# Build a deployable SOURCE bundle of the stand-alone Sonoff collector.
# Run this in the dev container; then scp the resulting tarball to the server and
# run ./deploy.sh inside the extracted directory.
set -euo pipefail

cd "$(dirname "$0")/.."            # repo root
ROOT="$PWD"

VERSION="$(grep -m1 -E '^version[[:space:]]*=' pyproject.toml | cut -d'"' -f2)"
[ -n "$VERSION" ] || { echo "Could not read version from pyproject.toml" >&2; exit 1; }

NAME="sonoff-collector-${VERSION}"
STAGE="dist/${NAME}"
TARBALL="dist/${NAME}.tar.gz"

rm -rf "$STAGE" "$TARBALL"
mkdir -p "$STAGE/systemd"

# self-contained source only — no secrets, no .git, no custom_components, no caches
cp -r standalone "$STAGE/"
cp pyproject.toml STANDALONE.md config.example.yaml "$STAGE/"
cp systemd/sonoff-collector.service "$STAGE/systemd/"
cp scripts/deploy.sh "$STAGE/"
chmod +x "$STAGE/deploy.sh"

# strip python caches and defensively drop any stray secret files
find "$STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$STAGE" -name '*.pyc' -delete 2>/dev/null || true
rm -f "$STAGE/devices.json" "$STAGE/credentials.yaml" "$STAGE/mqtt.yaml" 2>/dev/null || true

tar -C dist -czf "$TARBALL" "$NAME"
rm -rf "$STAGE"

echo "Built $ROOT/$TARBALL"
echo
echo "Deploy:"
echo "  scp $TARBALL user@server:~/"
echo "  ssh user@server"
echo "  tar xzf ${NAME}.tar.gz && cd ${NAME} && ./deploy.sh"
