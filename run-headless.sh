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
# NOTE: REI_USERNAME and REI_PASSWORD must be set in .env
#       for auto-login to work (no manual login in headless mode!)
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

# Check for credentials in .env
if ! grep -q "REI_USERNAME" .env 2>/dev/null || ! grep -q "REI_PASSWORD" .env 2>/dev/null; then
    echo "WARNING: REI_USERNAME and/or REI_PASSWORD not found in .env"
    echo "Auto-login will not work without credentials!"
    echo ""
    read -p "Continue anyway? (y/N): " response
    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        echo "Aborted. Add credentials to .env first."
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
