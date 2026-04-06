# Ops Automation Hardening

This repo now includes two operational hardening paths for Paradise Automator:

1. A watchdog that triggers the existing manual recovery flow when the daily run is overdue.
2. A pre-run restart timer that refreshes the service shortly before the report window.

## Watchdog

Files:

- [scripts/auto_recover_if_overdue.py](/root/src/paradise/paradise-automator-dev/scripts/auto_recover_if_overdue.py)
- [ops/systemd/paradise-automator-autorecover.service](/root/src/paradise/paradise-automator-dev/ops/systemd/paradise-automator-autorecover.service)
- [ops/systemd/paradise-automator-autorecover.timer](/root/src/paradise/paradise-automator-dev/ops/systemd/paradise-automator-autorecover.timer)

Behavior:

- Reads `automation_state.json`
- Compares `next_expected_run` to the current UTC time
- Fires `scripts/manual_recovery.sh daily` when the run is overdue past the grace period
- Logs each evaluation and recovery result to `logs/auto_recover_if_overdue.log`

Default grace period:

- `15` minutes
- Override with `AUTO_RECOVER_GRACE_MINUTES`

## Pre-Run Restart

Files:

- [ops/systemd/paradise-automator-prerun-restart.service](/root/src/paradise/paradise-automator-dev/ops/systemd/paradise-automator-prerun-restart.service)
- [ops/systemd/paradise-automator-prerun-restart.timer](/root/src/paradise/paradise-automator-dev/ops/systemd/paradise-automator-prerun-restart.timer)

Behavior:

- Restarts `paradise-automator.service` every day at `12:45`
- The timing is intentionally before the daily run window to clear stale browser state
- The restart is idempotent because `systemctl restart` is safe even if the service is already healthy

## Verification

Install the units on the host with:

```bash
sudo install -m 755 scripts/auto_recover_if_overdue.py /opt/paradise/paradise-automator/scripts/auto_recover_if_overdue.py
sudo install -m 644 ops/systemd/paradise-automator-autorecover.service /etc/systemd/system/
sudo install -m 644 ops/systemd/paradise-automator-autorecover.timer /etc/systemd/system/
sudo install -m 644 ops/systemd/paradise-automator-prerun-restart.service /etc/systemd/system/
sudo install -m 644 ops/systemd/paradise-automator-prerun-restart.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now paradise-automator-autorecover.timer
sudo systemctl enable --now paradise-automator-prerun-restart.timer
```

After installing the units on the host, verify with:

```bash
systemctl status paradise-automator-autorecover.timer
systemctl status paradise-automator-prerun-restart.timer
systemctl list-timers --all | rg 'paradise-automator'
```

To dry-run the watchdog logic without changing the service state:

```bash
/opt/paradise/paradise-automator/venv/bin/python /opt/paradise/paradise-automator/scripts/auto_recover_if_overdue.py --dry-run
```

If you want to test the true overdue path, set `next_expected_run` in a copy of `automation_state.json` to a timestamp older than the grace period and run the script against that copy with `--state-file`. Use `--force` only when you intentionally want to invoke the full recovery flow even if the state file is not overdue yet.
