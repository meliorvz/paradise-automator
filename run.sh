#!/bin/bash
# ============================================================
# REI Cloud Automation - HEADED MODE (Desktop/GUI)
# ============================================================
# Run this from the VPS desktop GUI or locally where you can
# see a browser window. Good for first-time setup or debugging.
#
# Usage:
#   ./run.sh           # Production (daily at 06:01)
#   ./run.sh --test    # Test mode (every 5 minutes)
#   ./run.sh --run-now # Run report immediately then schedule
#   ./run.sh --record  # Record workflow (development only)
#
# For SSH/headless operation, use: ./run-headless.sh
# ============================================================

# Auto-detect Python executable
if [ -f "venv/bin/python" ]; then
    PYTHON="venv/bin/python"
elif [ -f "venv/bin/python3" ]; then
    PYTHON="venv/bin/python3"
elif command -v python3 &> /dev/null; then
    PYTHON="python3"
else
    echo "Error: Python 3 not found."
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cd "$SCRIPT_DIR"
"$PYTHON" rei_cloud_automation.py "$@"
