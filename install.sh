#!/usr/bin/env bash
# Automated installation script for Enterprise Email Ingestion Gateway
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================================"
echo "   Enterprise Email Ingestion Gateway - Setup Installer   "
echo "============================================================"

# Find Python 3 binary
if command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_CMD="python"
else
    echo "[ERROR] Python 3 is not installed or not in PATH."
    exit 1
fi

# Run the cross-platform installer
exec "$PYTHON_CMD" "$SCRIPT_DIR/install.py" "$@"
