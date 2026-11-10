#!/usr/bin/env bash
# Starts the Fairy builder and opens it in the browser. Ctrl+C stops it.
# Usage: ./start.sh [--lan]      (--lan: also reachable from a phone on your network, no password)
set -euo pipefail
cd "$(dirname "$0")"
PORT=8780

[ -x .venv/bin/python ] || { python3 -m venv .venv && .venv/bin/pip -q install bleak; }

# a previous builder or the desktop window would hold the light's single Bluetooth connection
pkill -f "builder.py" 2>/dev/null || true
pkill -f "fairy_gui.py" 2>/dev/null || true
bluetoothctl devices 2>/dev/null | awk '/Hello Fairy/ {print $2}' | while read -r mac; do
  bluetoothctl disconnect "$mac" >/dev/null 2>&1 || true
done

(sleep 1.2; xdg-open "http://localhost:$PORT" >/dev/null 2>&1 || true) &
exec .venv/bin/python builder.py --port "$PORT" "$@"
