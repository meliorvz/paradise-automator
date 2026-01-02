#!/bin/bash
# REI Cloud Automation wrapper script
# Uses the correct Python installation with Playwright

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
