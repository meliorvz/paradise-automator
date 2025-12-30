#!/bin/bash
# REI Cloud Automation wrapper script
# Uses the correct Python installation with Playwright

PYTHON="/Library/Frameworks/Python.framework/Versions/3.11/bin/python3"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cd "$SCRIPT_DIR"
"$PYTHON" rei_cloud_automation.py "$@"
