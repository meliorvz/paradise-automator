#!/usr/bin/env python3
"""Run a one-off Paradise Automator report without starting the scheduler loop."""

import argparse
from pathlib import Path
import sys

APP_DIR = Path(__file__).resolve().parent.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import rei_cloud_automation as automation


def is_logged_in() -> bool:
    """Return True when the current page looks like an authenticated REI session."""
    try:
        return "Dashboard" in automation.page.url or (
            "reimasterapps.com.au" in automation.page.url
            and "b2clogin" not in automation.page.url
        )
    except Exception:
        return False


def get_success_marker(report_type: str) -> str | None:
    state = automation.load_state()
    if report_type == "daily":
        return state.get("last_successful_run")
    return state.get("last_successful_weekly_run")


def close_browser() -> None:
    if automation.context:
        try:
            automation.context.close()
        except Exception as exc:
            automation.logger.warning("Failed to close browser context cleanly: %s", exc)
    if automation.playwright_instance:
        try:
            automation.playwright_instance.stop()
        except Exception as exc:
            automation.logger.warning("Failed to stop Playwright cleanly: %s", exc)


def ensure_logged_in_session() -> None:
    automation.setup_browser()
    automation.page.goto(automation.REI_CLOUD_URL, timeout=60000)

    if is_logged_in():
        return

    if automation.REI_USERNAME and automation.REI_PASSWORD:
        automation.logger.info(
            "Credentials found in .env - attempting auto-login for one-off run..."
        )
        if automation.auto_login():
            automation.page.wait_for_timeout(3000)
            if is_logged_in():
                return

    raise RuntimeError("Unable to establish a logged-in REI session for one-off run.")


def run_once(report_type: str) -> None:
    before = get_success_marker(report_type)

    if report_type == "daily":
        automation.run_daily_report()
    else:
        automation.run_weekly_report()

    after = get_success_marker(report_type)
    if not after or after == before:
        raise RuntimeError(
            f"One-off {report_type} run did not update automation_state.json."
        )

    automation.logger.info("One-off %s run recorded success at %s", report_type, after)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a one-off Paradise Automator report."
    )
    parser.add_argument("report_type", choices=("daily", "weekly"))
    args = parser.parse_args()

    try:
        ensure_logged_in_session()
        run_once(args.report_type)
        return 0
    except Exception as exc:
        automation.logger.error("One-off %s run failed: %s", args.report_type, exc)
        return 1
    finally:
        close_browser()


if __name__ == "__main__":
    sys.exit(main())
