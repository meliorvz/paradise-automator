#!/bin/bash
# ============================================================
# REI Cloud Automation - HEADLESS MODE
# ============================================================
# Run this via SSH when you don't have a desktop/GUI available.
# Uses xvfb-run to create a virtual display for the browser.
#
# Usage:
#   ./run-headless.sh              # Production (daily at 13:00, weekly Sat 08:00)
#   ./run-headless.sh --test       # Test mode (every 5 minutes)
#   ./run-headless.sh --run-now    # Run daily report immediately then schedule
#   ./run-headless.sh --run-weekly # Run weekly report immediately then schedule
#
# NOTE: Requires xvfb to be installed:
#   sudo apt install xvfb
#
# NOTE: Auto-login can use either plain REI_* values in .env or
#       1Password config (OP_SERVICE_ACCOUNT_TOKEN plus REI_1PASSWORD_* or op:// refs).
#       Manual login is not available in headless mode.
# ============================================================

echo "============================================================"
echo "  REI CLOUD AUTOMATION - HEADLESS MODE"
echo "============================================================"
echo ""

# Check for xvfb-run
if ! command -v xvfb-run &> /dev/null; then
    echo "ERROR: xvfb-run not found!"
    echo "Install it with: sudo apt install xvfb"
    exit 1
fi

# Check for auth config in .env
if ! grep -Eq "^(REI_USERNAME|REI_PASSWORD|OP_SERVICE_ACCOUNT_TOKEN|REI_1PASSWORD_ITEM|REI_1PASSWORD_VAULT)=" .env 2>/dev/null; then
    echo "WARNING: No REI auth config or 1Password config found in .env"
    echo "Headless auto-login will not work without credentials!"
    echo ""
    read -p "Continue anyway? (y/N): " response
    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        echo "Aborted. Add REI credentials or 1Password config to .env first."
        exit 1
    fi
fi

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

echo "Starting in headless mode with xvfb-run..."
echo ""

# Run with xvfb-run (virtual display)
xvfb-run --auto-servernum --server-args="-screen 0 1280x800x24" "$PYTHON" rei_cloud_automation.py "$@"
