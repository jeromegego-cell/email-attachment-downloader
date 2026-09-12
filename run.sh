#!/usr/bin/env bash
# Launcher script for Enterprise Email Ingestion Gateway
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/.venv/bin/email-ingestion" ]; then
    exec "$SCRIPT_DIR/.venv/bin/email-ingestion" "$@"
else
    exec python3 "$SCRIPT_DIR/run.py" "$@"
fi
