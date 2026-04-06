# Automation Hardening Tickets

## Ticket 1: Auth Preflight Before Scheduled Reports

- Status: Implemented
- Scope: `rei_cloud_automation.py`
- Goal: Every daily and weekly report run must verify that the browser is on an authenticated REI page before trying to click report links.
- Acceptance criteria:
- Navigating to the report list must explicitly verify the page is not a login page.
- The run must verify that `Arrival Report` is visible before continuing.
- If the preflight fails, the run must trigger a recovery path instead of timing out on `page.click("text=Arrival Report")`.
- Failures must log the current URL and the failed preflight reason.

## Ticket 2: Fresh-Context Reauth And Retry

- Status: Implemented
- Scope: `rei_cloud_automation.py`
- Goal: If auth is stale or page state is inconsistent, recover with a fresh Playwright browser context rather than continuing on the existing page.
- Acceptance criteria:
- Add a recovery path that closes the current context, launches a fresh persistent context, and reopens REI.
- Reauth must be followed by a verified authenticated page check, not just a URL check.
- Daily and weekly runs must retry once after fresh-context recovery.
- Heartbeat recovery must also use the verified reauth flow.

## Ticket 3: Missed-Run Auto-Recovery

- Status: Implemented
- Scope: `scripts/manual_recovery.sh`, `scripts/manual_report_runner.py`, systemd timer/unit files, docs
- Goal: If a scheduled run is overdue, the host should invoke the recovery wrapper automatically.
- Acceptance criteria:
- Add a one-shot systemd service/timer or equivalent watchdog trigger that runs the manual recovery wrapper.
- The recovery path must only fire when `automation_state.json` shows the scheduled run is overdue past a defined grace period.
- Recovery actions and outcomes must be logged clearly.
- The timer/service must be documented with install and verification steps.

## Ticket 4: Pre-Run Service Restart

- Status: Implemented
- Scope: systemd timer/unit files, docs
- Goal: Restart the long-running Paradise Automator service shortly before the report window to refresh browser state.
- Acceptance criteria:
- Add a systemd timer/unit that restarts `paradise-automator.service` before the daily run window.
- The restart timing must be documented and easy to adjust.
- The restart path must be idempotent and safe if the service is already healthy.
- Deployment steps must include enabling and verifying the restart timer.
