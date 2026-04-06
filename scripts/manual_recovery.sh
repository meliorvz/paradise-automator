#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
SERVICE_NAME="paradise-automator.service"
PYTHON_BIN="$APP_DIR/venv/bin/python"
RUNNER="$APP_DIR/scripts/manual_report_runner.py"
LOG_DIR="$APP_DIR/logs"
SERVICE_STOPPED=0

usage() {
    cat <<'EOF'
Usage:
  sudo ./scripts/manual_recovery.sh daily
  sudo ./scripts/manual_recovery.sh weekly
  sudo ./scripts/manual_recovery.sh status

Actions:
  daily   Stop the systemd service, run a one-off daily report, restart service
  weekly  Stop the systemd service, run a one-off weekly report, restart service
  status  Show current paradise-automator systemd status
EOF
}

log() {
    printf '[manual-recovery] %s\n' "$*"
}

require_root() {
    if [[ "$(id -u)" -ne 0 ]]; then
        log "Run this script as root so it can control systemd and use /root browser state."
        exit 1
    fi
}

service_state() {
    systemctl show -p ActiveState --value "$SERVICE_NAME"
}

service_substate() {
    systemctl show -p SubState --value "$SERVICE_NAME"
}

wait_for_state() {
    local desired_csv="$1"
    local timeout="${2:-30}"
    local state=""
    local elapsed=0

    while (( elapsed < timeout )); do
        state="$(service_state)"
        case ",${desired_csv}," in
            *,"${state}",*)
                return 0
                ;;
        esac
        sleep 1
        ((elapsed+=1))
    done

    log "Timed out waiting for service state ${desired_csv}. Current: $(service_state)/$(service_substate)"
    return 1
}

cleanup() {
    local exit_code=$?

    if [[ "$SERVICE_STOPPED" -eq 1 ]] && [[ "$(service_state)" != "active" ]]; then
        log "Ensuring ${SERVICE_NAME} is started again after recovery attempt..."
        systemctl start "$SERVICE_NAME" || true
    fi

    exit "$exit_code"
}

stop_service() {
    local state
    state="$(service_state)"

    if [[ "$state" == "inactive" || "$state" == "failed" ]]; then
        log "${SERVICE_NAME} is already ${state}."
        SERVICE_STOPPED=1
        return
    fi

    log "Stopping ${SERVICE_NAME}..."
    SERVICE_STOPPED=1
    systemctl stop --no-block "$SERVICE_NAME"

    if ! wait_for_state "inactive,failed" 20; then
        log "Service is stuck in $(service_state)/$(service_substate); force-killing lingering processes..."
        if ! systemctl kill --kill-whom=all --signal=KILL "$SERVICE_NAME"; then
            log "systemctl kill returned non-zero; re-checking service state before failing."
        fi
        wait_for_state "inactive,failed" 10
    fi
}

run_oneoff() {
    local report_type="$1"
    local timestamp
    local log_file

    mkdir -p "$LOG_DIR"
    timestamp="$(date -u +%Y%m%d_%H%M%S)"
    log_file="$LOG_DIR/manual_recovery_${report_type}_${timestamp}.log"

    log "Running one-off ${report_type} report. Log: ${log_file}"
    (
        cd "$APP_DIR"
        xvfb-run -a "$PYTHON_BIN" "$RUNNER" "$report_type"
    ) 2>&1 | tee "$log_file"
}

start_service() {
    log "Starting ${SERVICE_NAME}..."
    systemctl start "$SERVICE_NAME"
    wait_for_state "active" 20
    log "${SERVICE_NAME} is active."
}

show_status() {
    systemctl status "$SERVICE_NAME" --no-pager
}

main() {
    local action="${1:-}"

    case "$action" in
        daily|weekly)
            require_root
            trap cleanup EXIT

            if [[ ! -x "$PYTHON_BIN" ]]; then
                log "Python runtime not found at ${PYTHON_BIN}"
                exit 1
            fi
            if [[ ! -f "$RUNNER" ]]; then
                log "Runner script not found at ${RUNNER}"
                exit 1
            fi

            stop_service
            run_oneoff "$action"
            start_service
            show_status
            ;;
        status)
            show_status
            ;;
        *)
            usage
            exit 1
            ;;
    esac
}

main "$@"
