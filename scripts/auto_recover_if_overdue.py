#!/usr/bin/env python3
"""Trigger the existing manual recovery flow when the daily run is overdue.

This script is intended to be run from systemd on a schedule. It checks the
current automation state, compares the next expected daily run to the current
time, and invokes the existing manual recovery wrapper when the run is overdue
past a configurable grace period.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.8 fallback
    ZoneInfo = None  # type: ignore[assignment]


DEFAULT_APP_DIR = Path("/opt/paradise/paradise-automator")
DEFAULT_STATE_FILE = DEFAULT_APP_DIR / "automation_state.json"
DEFAULT_RECOVERY_SCRIPT = DEFAULT_APP_DIR / "scripts" / "manual_recovery.sh"
DEFAULT_LOG_FILE = DEFAULT_APP_DIR / "logs" / "auto_recover_if_overdue.log"
BRISBANE_TZ_NAME = "Australia/Brisbane"


@dataclass
class RecoveryDecision:
    should_recover: bool
    reason: str
    next_expected_run: Optional[datetime] = None


def log(message: str) -> None:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{timestamp}] {message}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recover Paradise Automator when the scheduled daily run is overdue."
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=DEFAULT_STATE_FILE,
        help="Path to automation_state.json",
    )
    parser.add_argument(
        "--recovery-script",
        type=Path,
        default=DEFAULT_RECOVERY_SCRIPT,
        help="Path to scripts/manual_recovery.sh",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=DEFAULT_LOG_FILE,
        help="Append-only log file for watchdog activity",
    )
    parser.add_argument(
        "--grace-minutes",
        type=int,
        default=int(os.getenv("AUTO_RECOVER_GRACE_MINUTES", "15")),
        help="Minutes after the next expected daily run before recovery fires",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run recovery even if the state file does not yet show an overdue run",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Evaluate overdue state and exit without invoking recovery",
    )
    return parser.parse_args()


def ensure_log_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        raise RuntimeError(f"Unable to parse state file {path}: {exc}") from exc


def get_brisbane_tz():
    if ZoneInfo is not None:
        return ZoneInfo(BRISBANE_TZ_NAME)
    # Fallback if zoneinfo data is unavailable.
    return timezone(timedelta(hours=10))


def parse_state_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def evaluate_overdue(state: dict, grace_minutes: int) -> RecoveryDecision:
    next_expected_raw = state.get("next_expected_run")
    last_success_raw = state.get("last_successful_run")

    next_expected = parse_state_timestamp(next_expected_raw)
    last_success = parse_state_timestamp(last_success_raw)
    now = datetime.now(timezone.utc)

    if next_expected is None:
        return RecoveryDecision(False, "next_expected_run missing; nothing to recover")

    deadline = next_expected + timedelta(minutes=grace_minutes)
    if now <= deadline:
        return RecoveryDecision(
            False,
            f"daily run not overdue yet; deadline is {deadline.isoformat()}",
            next_expected,
        )

    if last_success is not None and last_success >= next_expected:
        return RecoveryDecision(
            False,
            "a successful daily run already happened after the current deadline",
            next_expected,
        )

    return RecoveryDecision(
        True,
        f"daily run overdue; deadline {deadline.isoformat()} passed at {now.isoformat()}",
        next_expected,
    )


def append_watchdog_log(log_file: Path, message: str) -> None:
    ensure_log_dir(log_file)
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now(timezone.utc).isoformat()} {message}\n")


def run_recovery(recovery_script: Path, report_type: str) -> subprocess.CompletedProcess[str]:
    if not recovery_script.exists():
        raise RuntimeError(f"Recovery script does not exist: {recovery_script}")

    return subprocess.run(
        [str(recovery_script), report_type],
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> int:
    args = parse_args()
    ensure_log_dir(args.log_file)

    try:
        state = load_state(args.state_file)
    except Exception as exc:
        append_watchdog_log(args.log_file, f"state-read-failed reason={exc}")
        raise

    decision = evaluate_overdue(state, args.grace_minutes)
    append_watchdog_log(
        args.log_file,
        f"evaluated should_recover={decision.should_recover} reason={decision.reason} "
        f"next_expected_run={decision.next_expected_run.isoformat() if decision.next_expected_run else 'none'}",
    )

    if not decision.should_recover and not args.force:
        log(decision.reason)
        return 0

    if args.dry_run:
        log(f"Dry run only: would trigger recovery because {decision.reason}")
        return 0

    log(f"Triggering recovery: {decision.reason}")
    result = run_recovery(args.recovery_script, "daily")

    append_watchdog_log(
        args.log_file,
        f"recovery-returncode={result.returncode} stdout={result.stdout.strip()!r} stderr={result.stderr.strip()!r}",
    )

    if result.returncode != 0:
        log(f"Recovery failed with exit code {result.returncode}")
        if result.stdout:
            sys.stdout.write(result.stdout)
        if result.stderr:
            sys.stderr.write(result.stderr)
        return result.returncode

    log("Recovery completed successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
