# Manual Recovery Playbook

Use this when `paradise-automator` misses a scheduled run, gets stuck, or you need to trigger a clean one-off report without leaving a second scheduler process behind.

## Commands

Run these on the VPS as `root`:

```bash
cd /opt/paradise/paradise-automator
sudo ./scripts/manual_recovery.sh daily
```

```bash
cd /opt/paradise/paradise-automator
sudo ./scripts/manual_recovery.sh weekly
```

```bash
cd /opt/paradise/paradise-automator
sudo ./scripts/manual_recovery.sh status
```

## What The Script Does

For `daily` or `weekly`, the recovery script:

1. Stops `paradise-automator.service`
2. Waits for shutdown and force-kills lingering Playwright processes if the unit gets stuck in `deactivating`
3. Runs a one-off report via `scripts/manual_report_runner.py`
4. Verifies the run updated `automation_state.json`
5. Restarts `paradise-automator.service`
6. Prints final `systemctl status`

This avoids the old problem where `--run-now` starts a manual report but then leaves a second scheduler process running.

## Logs And Verification

- Recovery wrapper logs: `logs/manual_recovery_<daily|weekly>_<timestamp>.log`
- Main automation log: `automation.log`
- State file: `automation_state.json`

After a successful `daily` run, you should see:

- Fresh files under `downloads/`
- `last_successful_run` updated in `automation_state.json`
- `next_expected_run` moved to the next day
- `paradise-automator.service` back to `active (running)`

## Typical Use Case

If the bot missed the daily run on Saturday, April 4, 2026:

```bash
cd /opt/paradise/paradise-automator
sudo ./scripts/manual_recovery.sh daily
```

That will perform the same recovery flow manually executed on April 4, 2026:

- stop service
- clean up stuck browser processes if needed
- run one-off daily report
- restart service
