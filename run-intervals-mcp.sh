#!/bin/sh
# Startet garmin-mcp-bridge (intervals.icu) mit dem Key aus .env.
# Wird von .mcp.json aufgerufen. Keine Keys hier eintragen!
DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$DIR/.env" ]; then
  set -a
  . "$DIR/.env"
  set +a
fi
exec "$DIR/.venv/bin/python" -m garmin_mcp_bridge.server
