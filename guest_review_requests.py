#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import sqlite3
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

load_dotenv()

LOGGER = logging.getLogger("guest_review_requests")
DEFAULT_COMMS_API_URL = os.getenv(
    "COMMS_API_URL", "https://comms.paradisestayz.com.au/api/integrations/v1/send"
)
DEFAULT_COMMS_PROVIDER = "integration_api"
COMMS_API_KEY = os.getenv("COMMS_API_KEY", "").strip()

DEFAULT_DB_PATH = Path(
    os.getenv("GUEST_REVIEW_REQUESTS_DB_PATH", "state/guest_review_requests.sqlite3")
)
DEFAULT_TEMPLATE_KEY = os.getenv(
    "GUEST_REVIEW_REQUEST_TEMPLATE_KEY", "guest_review_request_v1"
)
DEFAULT_RULE_KEY = os.getenv("GUEST_REVIEW_REQUEST_RULE_KEY", "REVIEW_REQUEST")
DEFAULT_TEMPLATE_PATH = Path(
    os.getenv("GUEST_REVIEW_REQUEST_TEMPLATE_PATH", "templates/guest_review_request_v1.txt")
)
LOG_PATH = Path(os.getenv("GUEST_REVIEW_REQUEST_LOG_PATH", "logs/guest_review_requests.log"))
PHONE_INPUT_RE = re.compile(r"(?<!\w)(?:\+?61|0)\s*4(?:[\s()-]*\d){8}(?!\w)")


def configure_logging() -> None:
    if LOGGER.handlers:
        return

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOGGER.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    file_handler = logging.FileHandler(LOG_PATH)
    file_handler.setFormatter(formatter)
    LOGGER.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    LOGGER.addHandler(stream_handler)


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def compact(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def first_value(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = compact(row.get(key))
        if value:
            return value
    return ""


def normalize_iso_date(value: Any) -> str | None:
    text = compact(value)
    if not text:
        return None

    formats = (
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d %B %Y",
        "%d %b %Y",
    )
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    raise ValueError(f"Unsupported date format: {text}")


def normalize_phone(value: Any) -> tuple[str | None, str | None]:
    raw = compact(value)
    if not raw:
        return None, "missing_phone"

    cleaned = re.sub(r"[^\d+]", "", raw)
    if cleaned.startswith("00"):
        cleaned = f"+{cleaned[2:]}"

    if cleaned.startswith("+"):
        digits = re.sub(r"\D", "", cleaned[1:])
        candidate = f"+{digits}"
    else:
        digits = re.sub(r"\D", "", cleaned)
        candidate = digits
        if len(candidate) == 10 and candidate.startswith("04"):
            candidate = f"+61{candidate[1:]}"
        elif len(candidate) == 9 and candidate.startswith("4"):
            candidate = f"+61{candidate}"
        elif candidate.startswith("614") and len(candidate) == 11:
            candidate = f"+{candidate}"
        elif candidate.startswith("61") and len(candidate) == 11:
            candidate = f"+{candidate}"

    if re.fullmatch(r"\+614\d{8}", candidate or ""):
        return candidate, None

    return None, "invalid_phone"


def parse_name_and_phone(raw_input: str) -> tuple[str, str]:
    raw_text = compact(raw_input)
    if not raw_text:
        raise ValueError("Raw input must contain a guest name and phone number.")

    matches = list(PHONE_INPUT_RE.finditer(raw_text))
    if not matches:
        raise ValueError("Could not find a valid Australian mobile number in the input.")
    if len(matches) > 1:
        raise ValueError("Found multiple phone numbers in the input; provide exactly one.")

    match = matches[0]
    phone_text = match.group(0)
    name_text = f"{raw_text[:match.start()]} {raw_text[match.end():]}"
    name_text = re.sub(r"\s+", " ", name_text).strip(" \t\r\n,;:-")
    if not name_text:
        raise ValueError("Could not determine the guest name from the input.")
    return name_text, phone_text


class SafeFormatDict(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return ""


def load_template_text(template_path: Path | None = None) -> str:
    template_body = compact(os.getenv("GUEST_REVIEW_REQUEST_TEMPLATE_BODY"))
    if template_body:
        return template_body

    path = template_path or DEFAULT_TEMPLATE_PATH
    if path.exists():
        return path.read_text(encoding="utf-8").strip()

    raise RuntimeError(
        "No guest review request template configured. "
        "Set GUEST_REVIEW_REQUEST_TEMPLATE_BODY, create "
        f"{path}, or pass --message-body during prepare."
    )


def render_message(template_text: str, payload: dict[str, Any]) -> str:
    values = SafeFormatDict(
        {
            "booking_ref": compact(payload.get("booking_ref")),
            "guest_name": compact(payload.get("guest_name")),
            "guest_phone_e164": compact(payload.get("guest_phone_e164")),
            "check_in_date": compact(payload.get("check_in_date")),
            "check_out_date": compact(payload.get("check_out_date")),
        }
    )
    rendered = template_text
    for key, value in values.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    rendered = rendered.format_map(values).strip()
    if not rendered:
        raise RuntimeError("Rendered guest review request message is empty.")
    return rendered


def make_request_id() -> str:
    return f"grr_{uuid.uuid4().hex}"


def make_event_id() -> str:
    return f"grre_{uuid.uuid4().hex}"


def make_dedupe_key(
    guest_phone_e164: str | None,
) -> str:
    normalized_phone = compact(guest_phone_e164)
    if not normalized_phone:
        raise ValueError("guest_phone_e164 is required for dedupe")
    return f"phone:{normalized_phone}"


def row_to_public_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "rule_key": row["rule_key"],
        "channel": row["channel"],
        "booking_ref": row["booking_ref"],
        "booking_id": row["booking_id"],
        "stay_id": row["stay_id"],
        "guest_id": row["guest_id"],
        "property_id": row["property_id"],
        "unit_id": row["unit_id"],
        "guest_name": row["guest_name"],
        "guest_phone_e164": row["guest_phone_e164"],
        "check_out_date": row["check_out_date"],
        "template_key": row["template_key"],
        "message_body": row["message_body"],
        "status": row["status"],
        "provider": row["provider"],
        "provider_message_id": row["provider_message_id"],
        "sent_at": row["sent_at"],
        "last_error": row["last_error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=False))


def render_table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    if not rows:
        return ""

    widths = {column: len(column) for column in columns}
    for row in rows:
        for column in columns:
            widths[column] = max(widths[column], len(compact(row.get(column))))

    header = " | ".join(column.ljust(widths[column]) for column in columns)
    separator = "-+-".join("-" * widths[column] for column in columns)
    body = [
        " | ".join(compact(row.get(column)).ljust(widths[column]) for column in columns)
        for row in rows
    ]
    return "\n".join([header, separator, *body])


class ReviewRequestStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._ensure_schema()

    def close(self) -> None:
        self.conn.close()

    def _ensure_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS review_requests (
                id TEXT PRIMARY KEY,
                dedupe_key TEXT NOT NULL UNIQUE,
                rule_key TEXT NOT NULL DEFAULT 'REVIEW_REQUEST',
                channel TEXT NOT NULL DEFAULT 'sms',
                booking_ref TEXT,
                booking_id TEXT,
                stay_id TEXT,
                guest_id TEXT,
                property_id TEXT,
                unit_id TEXT,
                template_key TEXT NOT NULL,
                guest_name TEXT,
                guest_phone_raw TEXT,
                guest_phone_e164 TEXT,
                check_in_date TEXT,
                check_out_date TEXT,
                status TEXT NOT NULL,
                message_body TEXT NOT NULL,
                provider TEXT,
                provider_message_id TEXT,
                sent_at TEXT,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS review_request_events (
                id TEXT PRIMARY KEY,
                review_request_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                actor TEXT NOT NULL,
                details_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(review_request_id) REFERENCES review_requests(id)
            );
            """
        )
        self.conn.execute("DROP INDEX IF EXISTS idx_review_requests_booking_template")
        self._ensure_columns(
            "review_requests",
            {
                "rule_key": "TEXT NOT NULL DEFAULT 'REVIEW_REQUEST'",
                "channel": "TEXT NOT NULL DEFAULT 'sms'",
                "booking_id": "TEXT",
                "stay_id": "TEXT",
                "guest_id": "TEXT",
                "property_id": "TEXT",
                "unit_id": "TEXT",
            },
        )
        self.conn.commit()

    def _ensure_columns(self, table_name: str, columns: dict[str, str]) -> None:
        existing = {
            row["name"]
            for row in self.conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        for column_name, column_type in columns.items():
            if column_name in existing:
                continue
            self.conn.execute(
                f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
            )

    def _record_event(
        self,
        review_request_id: str,
        event_type: str,
        actor: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO review_request_events (
                id,
                review_request_id,
                event_type,
                actor,
                details_json,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                make_event_id(),
                review_request_id,
                event_type,
                actor,
                json.dumps(details or {}, sort_keys=True),
                utc_now(),
            ),
        )

    def _find_existing(self, dedupe_key: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM review_requests WHERE dedupe_key = ?",
            (dedupe_key,),
        ).fetchone()

    def get_request(self, request_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM review_requests WHERE id = ?",
            (request_id,),
        ).fetchone()

    def get_request_by_dedupe_key(self, dedupe_key: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM review_requests WHERE dedupe_key = ?",
            (dedupe_key,),
        ).fetchone()

    def prepare_request(
        self,
        candidate: dict[str, Any],
        actor: str,
        force: bool = False,
        force_reason: str | None = None,
    ) -> str:
        template_key = compact(candidate["template_key"])
        booking_ref = compact(candidate.get("booking_ref")) or None
        dedupe_key = candidate["dedupe_key"]
        existing = self._find_existing(dedupe_key)
        now = utc_now()
        skip_reason = compact(candidate.get("skip_reason"))

        if existing and existing["status"] == "sent" and not force:
            self._record_event(
                existing["id"],
                "skipped_already_sent",
                actor,
                {
                    "booking_ref": existing["booking_ref"],
                    "template_key": existing["template_key"],
                },
            )
            self.conn.commit()
            return "already_sent"

        status = "skipped" if skip_reason else "pending_send"
        last_error = skip_reason or None

        if existing:
            self.conn.execute(
                """
                UPDATE review_requests
                SET dedupe_key = ?,
                    rule_key = ?,
                    channel = ?,
                    booking_ref = ?,
                    booking_id = ?,
                    stay_id = ?,
                    guest_id = ?,
                    property_id = ?,
                    unit_id = ?,
                    template_key = ?,
                    guest_name = ?,
                    guest_phone_raw = ?,
                    guest_phone_e164 = ?,
                    check_in_date = ?,
                    check_out_date = ?,
                    status = ?,
                    message_body = ?,
                    provider = CASE WHEN ? = 'pending_send' THEN NULL ELSE provider END,
                    provider_message_id = CASE WHEN ? = 'pending_send' THEN NULL ELSE provider_message_id END,
                    sent_at = CASE WHEN ? = 'pending_send' THEN NULL ELSE sent_at END,
                    last_error = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    dedupe_key,
                    candidate["rule_key"],
                    candidate["channel"],
                    booking_ref,
                    candidate.get("booking_id"),
                    candidate.get("stay_id"),
                    candidate.get("guest_id"),
                    candidate.get("property_id"),
                    candidate.get("unit_id"),
                    template_key,
                    candidate.get("guest_name"),
                    candidate.get("guest_phone_raw"),
                    candidate.get("guest_phone_e164"),
                    candidate.get("check_in_date"),
                    candidate.get("check_out_date"),
                    status,
                    candidate["message_body"],
                    status,
                    status,
                    status,
                    last_error,
                    now,
                    existing["id"],
                ),
            )

            if force and compact(force_reason):
                self._record_event(
                    existing["id"],
                    "force_resend_requested",
                    actor,
                    {"reason": force_reason},
                )
            elif status == "pending_send" and existing["status"] != "pending_send":
                self._record_event(existing["id"], "queued", actor, {"status": status})
            elif status == "skipped" and (
                existing["status"] != "skipped" or compact(existing["last_error"]) != skip_reason
            ):
                self._record_event(
                    existing["id"],
                    f"skipped_{skip_reason}",
                    actor,
                    {"reason": skip_reason},
                )

            self.conn.commit()
            return "queued" if status == "pending_send" else f"skipped:{skip_reason}"

        request_id = make_request_id()
        self.conn.execute(
            """
            INSERT INTO review_requests (
                id,
                dedupe_key,
                rule_key,
                channel,
                booking_ref,
                booking_id,
                stay_id,
                guest_id,
                property_id,
                unit_id,
                template_key,
                guest_name,
                guest_phone_raw,
                guest_phone_e164,
                check_in_date,
                check_out_date,
                status,
                message_body,
                provider,
                provider_message_id,
                sent_at,
                last_error,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request_id,
                dedupe_key,
                candidate["rule_key"],
                candidate["channel"],
                booking_ref,
                candidate.get("booking_id"),
                candidate.get("stay_id"),
                candidate.get("guest_id"),
                candidate.get("property_id"),
                candidate.get("unit_id"),
                template_key,
                candidate.get("guest_name"),
                candidate.get("guest_phone_raw"),
                candidate.get("guest_phone_e164"),
                candidate.get("check_in_date"),
                candidate.get("check_out_date"),
                status,
                candidate["message_body"],
                None,
                None,
                None,
                last_error,
                now,
                now,
            ),
        )
        if status == "pending_send":
            self._record_event(request_id, "queued", actor, {"status": status})
        else:
            self._record_event(
                request_id,
                f"skipped_{skip_reason}",
                actor,
                {"reason": skip_reason},
            )
        self.conn.commit()
        return "queued" if status == "pending_send" else f"skipped:{skip_reason}"

    def export_requests(self, status: str, actor: str) -> list[sqlite3.Row]:
        rows = self.conn.execute(
            """
            SELECT * FROM review_requests
            WHERE status = ?
            ORDER BY check_out_date IS NULL, check_out_date, created_at
            """,
            (status,),
        ).fetchall()
        for row in rows:
            self._record_event(row["id"], "exported", actor, {"status": status})
        self.conn.commit()
        return rows

    def list_requests(
        self,
        status: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[sqlite3.Row]:
        clauses: list[str] = []
        params: list[Any] = []

        if status:
            clauses.append("status = ?")
            params.append(status)

        if from_date:
            clauses.append("COALESCE(check_out_date, substr(created_at, 1, 10)) >= ?")
            params.append(from_date)

        if to_date:
            clauses.append("COALESCE(check_out_date, substr(created_at, 1, 10)) <= ?")
            params.append(to_date)

        query = "SELECT * FROM review_requests"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY updated_at DESC"
        return self.conn.execute(query, params).fetchall()

    def mark_sent(
        self,
        request_id: str,
        actor: str,
        provider: str | None = None,
        provider_message_id: str | None = None,
        event_type: str = "sent",
        event_details: dict[str, Any] | None = None,
    ) -> sqlite3.Row:
        row = self.get_request(request_id)
        if not row:
            raise ValueError(f"Unknown request id: {request_id}")

        now = utc_now()
        self.conn.execute(
            """
            UPDATE review_requests
            SET status = 'sent',
                provider = ?,
                provider_message_id = ?,
                sent_at = ?,
                last_error = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (
                provider,
                provider_message_id,
                now,
                now,
                request_id,
            ),
        )
        self._record_event(
            request_id,
            event_type,
            actor,
            event_details
            or {
                "provider": provider,
                "provider_message_id": provider_message_id,
            },
        )
        self.conn.commit()
        updated = self.get_request(request_id)
        if not updated:
            raise RuntimeError(f"Request disappeared after mark_sent: {request_id}")
        return updated

    def mark_failed(
        self,
        request_id: str,
        actor: str,
        reason: str,
        preserve_status: bool = False,
        event_details: dict[str, Any] | None = None,
    ) -> sqlite3.Row:
        row = self.get_request(request_id)
        if not row:
            raise ValueError(f"Unknown request id: {request_id}")

        new_status = row["status"] if preserve_status else "failed"
        now = utc_now()
        self.conn.execute(
            """
            UPDATE review_requests
            SET status = ?,
                last_error = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                new_status,
                reason,
                now,
                request_id,
            ),
        )
        self._record_event(
            request_id,
            "failed",
            actor,
            event_details or {"reason": reason},
        )
        self.conn.commit()
        updated = self.get_request(request_id)
        if not updated:
            raise RuntimeError(f"Request disappeared after mark_failed: {request_id}")
        return updated


def read_prepare_rows(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and isinstance(payload.get("requests"), list):
            return [dict(item) for item in payload["requests"]]
        if isinstance(payload, list):
            return [dict(item) for item in payload]
        raise ValueError("JSON input must be an array or an object with a requests array.")

    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            return [dict(row) for row in reader]

    raise ValueError("Prepare input file must be .json or .csv.")


def build_prepare_candidate(
    raw_row: dict[str, Any],
    rule_key: str,
    template_key: str,
    template_text: str | None,
    message_override: str | None = None,
) -> dict[str, Any]:
    guest_name = first_value(raw_row, "guest_name", "name") or None
    guest_phone_raw = first_value(raw_row, "guest_phone", "phone", "mobile") or None
    booking_ref = first_value(raw_row, "booking_ref", "booking", "reference") or None
    booking_id = first_value(raw_row, "booking_id") or booking_ref
    stay_id = first_value(raw_row, "stay_id") or None
    guest_id = first_value(raw_row, "guest_id") or None
    property_id = first_value(raw_row, "property_id") or None
    unit_id = first_value(raw_row, "unit_id") or None
    channel = first_value(raw_row, "channel") or "sms"
    check_in_date = normalize_iso_date(first_value(raw_row, "check_in_date", "checkin_date")) if first_value(raw_row, "check_in_date", "checkin_date") else None
    check_out_date = normalize_iso_date(first_value(raw_row, "check_out_date", "checkout_date", "date")) if first_value(raw_row, "check_out_date", "checkout_date", "date") else None

    guest_phone_e164, phone_error = normalize_phone(guest_phone_raw)
    inline_message = first_value(raw_row, "message_body")

    message_template = compact(message_override) or inline_message
    render_payload = {
        "booking_ref": booking_ref,
        "guest_name": guest_name,
        "guest_phone_e164": guest_phone_e164,
        "check_in_date": check_in_date,
        "check_out_date": check_out_date,
    }

    if message_template:
        message_body = render_message(message_template, render_payload)
    else:
        if not template_text:
            raise RuntimeError(
                "No message body supplied and no template configured for prepare."
            )
        message_body = render_message(template_text, render_payload)

    candidate = {
        "rule_key": compact(raw_row.get("rule_key")) or rule_key,
        "channel": channel,
        "booking_ref": booking_ref,
        "booking_id": booking_id,
        "stay_id": stay_id,
        "guest_id": guest_id,
        "property_id": property_id,
        "unit_id": unit_id,
        "template_key": compact(raw_row.get("template_key")) or template_key,
        "guest_name": guest_name,
        "guest_phone_raw": guest_phone_raw,
        "guest_phone_e164": guest_phone_e164,
        "check_in_date": check_in_date,
        "check_out_date": check_out_date,
        "message_body": message_body,
        "skip_reason": phone_error,
    }
    candidate["dedupe_key"] = make_dedupe_key(
        candidate["guest_phone_e164"],
    )
    return candidate


def resolve_prepare_rows(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.input:
        return read_prepare_rows(Path(args.input))

    return [
        {
            "booking_ref": args.booking_ref,
            "booking_id": args.booking_id,
            "stay_id": args.stay_id,
            "guest_id": args.guest_id,
            "property_id": args.property_id,
            "unit_id": args.unit_id,
            "guest_name": args.guest_name,
            "guest_phone": args.guest_phone,
            "check_in_date": args.check_in_date,
            "check_out_date": args.check_out_date,
            "channel": args.channel,
            "rule_key": args.rule_key,
            "template_key": args.template_key,
            "message_body": args.message_body,
        }
    ]


def extract_sms_message_id(response_json: dict[str, Any] | None) -> str | None:
    if not isinstance(response_json, dict):
        return None

    results = response_json.get("results")
    if not isinstance(results, list):
        return None

    for result in results:
        if not isinstance(result, dict):
            continue
        if result.get("channel") == "sms" and result.get("status") == "sent":
            return compact(result.get("messageId")) or None

    return None


def send_request_via_comms(row: sqlite3.Row) -> tuple[bool, str | None, str | None, str]:
    provider = DEFAULT_COMMS_PROVIDER
    channel = compact(row["channel"]) or "sms"
    if channel != "sms":
        return False, None, f"Unsupported channel for this CLI: {channel}", provider
    if not COMMS_API_KEY:
        return False, None, "COMMS_API_KEY is not configured", provider

    payload = {
        "channels": [channel],
        "to": [row["guest_phone_e164"]],
        "body": row["message_body"],
    }
    for key in ("stay_id", "booking_id", "guest_id", "property_id", "unit_id"):
        value = compact(row[key])
        if value:
            payload[key] = value

    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    try:
        response = session.post(
            DEFAULT_COMMS_API_URL,
            json=payload,
            headers={
                "x-integration-key": COMMS_API_KEY,
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        try:
            response_json = response.json()
        except Exception:
            response_json = None
        if response.status_code == 200 and isinstance(response_json, dict) and response_json.get("success"):
            return True, extract_sms_message_id(response_json), None, provider
        return False, None, compact(response.text) or "SMS send failed", provider
    except Exception as exc:
        return False, None, str(exc), provider
    finally:
        session.close()


def handle_prepare(args: argparse.Namespace) -> int:
    raw_rows = resolve_prepare_rows(args)
    template_text = None
    if not args.message_body:
        try:
            template_text = load_template_text(
                Path(args.template_path) if args.template_path else None
            )
        except RuntimeError as exc:
            needs_template = any(not compact(row.get("message_body")) for row in raw_rows)
            if needs_template:
                raise
            LOGGER.info("Skipping template load: %s", exc)

    store = ReviewRequestStore(Path(args.db_path))
    counts = Counter()
    try:
        for raw_row in raw_rows:
            candidate = build_prepare_candidate(
                raw_row=raw_row,
                rule_key=args.rule_key,
                template_key=args.template_key,
                template_text=template_text,
                message_override=args.message_body,
            )
            outcome = store.prepare_request(
                candidate,
                actor=args.actor,
                force=args.force,
                force_reason=args.reason,
            )
            counts[outcome] += 1
    finally:
        store.close()

    summary = {
        "queued": counts["queued"],
        "already_sent": counts["already_sent"],
        "skipped_missing_phone": counts["skipped:missing_phone"],
        "skipped_invalid_phone": counts["skipped:invalid_phone"],
        "total_input": len(raw_rows),
    }
    LOGGER.info("Prepare summary: %s", summary)
    print_json(summary)
    return 0


def handle_export(args: argparse.Namespace) -> int:
    store = ReviewRequestStore(Path(args.db_path))
    try:
        rows = store.export_requests(status=args.status, actor=args.actor)
        payload = {"requests": [row_to_public_dict(row) for row in rows]}
    finally:
        store.close()

    if args.format == "json":
        print_json(payload)
        return 0

    table_rows = payload["requests"]
    print(
        render_table(
            table_rows,
            [
                "id",
                "booking_ref",
                "guest_name",
                "guest_phone_e164",
                "check_out_date",
                "status",
            ],
        )
    )
    return 0


def handle_mark_sent(args: argparse.Namespace) -> int:
    store = ReviewRequestStore(Path(args.db_path))
    try:
        row = store.mark_sent(
            request_id=args.request_id,
            actor=args.actor,
            provider=args.provider,
            provider_message_id=args.provider_message_id,
        )
    finally:
        store.close()

    print_json({"request": row_to_public_dict(row)})
    return 0


def handle_mark_failed(args: argparse.Namespace) -> int:
    store = ReviewRequestStore(Path(args.db_path))
    try:
        row = store.mark_failed(
            request_id=args.request_id,
            actor=args.actor,
            reason=args.reason,
        )
    finally:
        store.close()

    print_json({"request": row_to_public_dict(row)})
    return 0


def handle_list(args: argparse.Namespace) -> int:
    from_date = normalize_iso_date(args.from_date) if args.from_date else None
    to_date = normalize_iso_date(args.to_date) if args.to_date else None

    store = ReviewRequestStore(Path(args.db_path))
    try:
        rows = store.list_requests(status=args.status, from_date=from_date, to_date=to_date)
        payload = {"requests": [row_to_public_dict(row) for row in rows]}
    finally:
        store.close()

    if args.format == "json":
        print_json(payload)
        return 0

    table = render_table(
        payload["requests"],
        [
            "id",
            "booking_ref",
            "guest_name",
            "guest_phone_e164",
            "check_out_date",
            "status",
            "provider",
            "sent_at",
            "last_error",
        ],
    )
    if table:
        print(table)
    return 0


def handle_send(args: argparse.Namespace) -> int:
    store = ReviewRequestStore(Path(args.db_path))
    counts = Counter()
    try:
        if args.request_id:
            rows = []
            row = store.get_request(args.request_id)
            if not row:
                raise ValueError(f"Unknown request id: {args.request_id}")
            rows.append(row)
        else:
            rows = store.list_requests(status=args.status, from_date=None, to_date=None)

        for row in rows:
            old_status = row["status"]
            if old_status != "pending_send":
                if not args.force:
                    counts["skipped_not_pending"] += 1
                    continue
                if not compact(args.reason):
                    raise ValueError("--reason is required when --force is used for send.")
                if old_status == "sent":
                    store._record_event(
                        row["id"],
                        "force_resend_requested",
                        args.actor,
                        {"reason": args.reason},
                    )
                    store.conn.commit()

            success, message_id, error, provider = send_request_via_comms(row)
            if success:
                event_type = "force_resend_sent" if args.force and old_status == "sent" else "sent"
                store.mark_sent(
                    request_id=row["id"],
                    actor=args.actor,
                    provider=provider,
                    provider_message_id=message_id,
                    event_type=event_type,
                    event_details={
                        "provider": provider,
                        "provider_message_id": message_id,
                        "reason": args.reason if args.force else None,
                    },
                )
                counts["sent"] += 1
            else:
                preserve_status = bool(args.force and old_status == "sent")
                store.mark_failed(
                    request_id=row["id"],
                    actor=args.actor,
                    reason=error or "SMS send failed",
                    preserve_status=preserve_status,
                    event_details={
                        "reason": error or "SMS send failed",
                        "provider": provider,
                        "forced": bool(args.force),
                    },
                )
                counts["failed"] += 1
    finally:
        store.close()

    LOGGER.info("Send summary: %s", dict(counts))
    print_json(dict(counts))
    return 0


def handle_send_one(args: argparse.Namespace) -> int:
    template_text = None
    if not args.message_body:
        template_text = load_template_text(
            Path(args.template_path) if args.template_path else None
        )

    raw_row = {
        "booking_ref": args.booking_ref,
        "booking_id": args.booking_id,
        "stay_id": args.stay_id,
        "guest_id": args.guest_id,
        "property_id": args.property_id,
        "unit_id": args.unit_id,
        "guest_name": args.guest_name,
        "guest_phone": args.guest_phone,
        "check_in_date": args.check_in_date,
        "check_out_date": args.check_out_date,
        "channel": args.channel,
        "rule_key": args.rule_key,
        "template_key": args.template_key,
        "message_body": args.message_body,
    }
    candidate = build_prepare_candidate(
        raw_row=raw_row,
        rule_key=args.rule_key,
        template_key=args.template_key,
        template_text=template_text,
        message_override=args.message_body,
    )

    store = ReviewRequestStore(Path(args.db_path))
    try:
        outcome = store.prepare_request(
            candidate,
            actor=args.actor,
            force=args.force,
            force_reason=args.reason,
        )
        row = store.get_request_by_dedupe_key(candidate["dedupe_key"])
        if not row:
            raise RuntimeError("Prepared request could not be found in the ledger.")

        if outcome == "already_sent" and not args.force:
            print_json(
                {
                    "result": "skipped_already_sent",
                    "request": row_to_public_dict(row),
                }
            )
            return 0

        if row["status"] == "skipped":
            print_json(
                {
                    "result": "skipped",
                    "request": row_to_public_dict(row),
                }
            )
            return 0

        success, message_id, error, provider = send_request_via_comms(row)
        if success:
            event_type = "force_resend_sent" if args.force and row["status"] == "sent" else "sent"
            updated = store.mark_sent(
                request_id=row["id"],
                actor=args.actor,
                provider=provider,
                provider_message_id=message_id,
                event_type=event_type,
                event_details={
                    "provider": provider,
                    "provider_message_id": message_id,
                    "reason": args.reason if args.force else None,
                },
            )
            print_json({"result": "sent", "request": row_to_public_dict(updated)})
            return 0

        preserve_status = bool(args.force and row["status"] == "sent")
        updated = store.mark_failed(
            request_id=row["id"],
            actor=args.actor,
            reason=error or "SMS send failed",
            preserve_status=preserve_status,
            event_details={
                "reason": error or "SMS send failed",
                "provider": provider,
                "forced": bool(args.force),
            },
        )
        print_json({"result": "failed", "request": row_to_public_dict(updated)})
        return 0
    finally:
        store.close()


def handle_send_raw(args: argparse.Namespace) -> int:
    raw_chunks = list(getattr(args, "raw_input", []) or [])
    raw_input = " ".join(raw_chunks).strip()
    if not raw_input:
        stdin_text = sys.stdin.read()
        raw_input = compact(stdin_text)
    guest_name, guest_phone = parse_name_and_phone(raw_input)
    args.guest_name = guest_name
    args.guest_phone = guest_phone
    return handle_send_one(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Guest review request queue and sender")
    parser.add_argument(
        "--db-path",
        default=str(DEFAULT_DB_PATH),
        help=f"SQLite DB path (default: {DEFAULT_DB_PATH})",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare", help="Queue manual guest review requests")
    prepare_parser.add_argument("--input", help="CSV or JSON file of requests to prepare")
    prepare_parser.add_argument("--booking-ref", help="Booking reference for duplicate protection")
    prepare_parser.add_argument("--booking-id", help="Future comms/nerve booking id")
    prepare_parser.add_argument("--stay-id", help="Future comms/nerve stay id")
    prepare_parser.add_argument("--guest-id", help="Future comms/nerve guest id")
    prepare_parser.add_argument("--property-id", help="Future comms/nerve property id")
    prepare_parser.add_argument("--unit-id", help="Future comms/nerve unit id")
    prepare_parser.add_argument("--guest-name", help="Guest display name")
    prepare_parser.add_argument("--guest-phone", help="Guest phone number, 04.. or E.164")
    prepare_parser.add_argument("--check-in-date", help="Check-in date (YYYY-MM-DD or DD/MM/YYYY)")
    prepare_parser.add_argument("--check-out-date", help="Check-out date (YYYY-MM-DD or DD/MM/YYYY)")
    prepare_parser.add_argument(
        "--rule-key",
        default=DEFAULT_RULE_KEY,
        help=f"Automation rule key to record (default: {DEFAULT_RULE_KEY})",
    )
    prepare_parser.add_argument(
        "--channel",
        choices=("sms",),
        default="sms",
        help="Channel to record for future comms compatibility (default: sms)",
    )
    prepare_parser.add_argument(
        "--template-key",
        default=DEFAULT_TEMPLATE_KEY,
        help=f"Template key to record (default: {DEFAULT_TEMPLATE_KEY})",
    )
    prepare_parser.add_argument(
        "--template-path",
        help=f"Template file path (default: {DEFAULT_TEMPLATE_PATH})",
    )
    prepare_parser.add_argument("--message-body", help="Use this exact message body instead of a template")
    prepare_parser.add_argument("--actor", default="cli_prepare", help="Actor name for audit events")
    prepare_parser.add_argument("--force", action="store_true", help="Explicitly requeue an already-sent request")
    prepare_parser.add_argument("--reason", help="Required with --force for resend auditing")
    prepare_parser.set_defaults(func=handle_prepare)

    export_parser = subparsers.add_parser("export", help="Export review requests")
    export_parser.add_argument("--status", default="pending_send", help="Status to export")
    export_parser.add_argument("--format", choices=("json", "table"), default="json")
    export_parser.add_argument("--actor", default="cli_export", help="Actor name for audit events")
    export_parser.set_defaults(func=handle_export)

    mark_sent_parser = subparsers.add_parser("mark-sent", help="Mark a request as sent")
    mark_sent_parser.add_argument("--request-id", required=True)
    mark_sent_parser.add_argument("--provider", default="openclaw")
    mark_sent_parser.add_argument("--provider-message-id")
    mark_sent_parser.add_argument("--actor", default="cli_mark_sent")
    mark_sent_parser.set_defaults(func=handle_mark_sent)

    mark_failed_parser = subparsers.add_parser("mark-failed", help="Mark a request as failed")
    mark_failed_parser.add_argument("--request-id", required=True)
    mark_failed_parser.add_argument("--reason", required=True)
    mark_failed_parser.add_argument("--actor", default="cli_mark_failed")
    mark_failed_parser.set_defaults(func=handle_mark_failed)

    list_parser = subparsers.add_parser("list", help="List review requests")
    list_parser.add_argument("--status")
    list_parser.add_argument("--from", dest="from_date")
    list_parser.add_argument("--to", dest="to_date")
    list_parser.add_argument("--format", choices=("json", "table"), default="table")
    list_parser.set_defaults(func=handle_list)

    send_parser = subparsers.add_parser(
        "send",
        help="Send pending requests directly through the configured integrations endpoint",
    )
    send_parser.add_argument("--request-id", help="Send exactly one request id")
    send_parser.add_argument(
        "--status",
        default="pending_send",
        help="Status to send when request-id is not supplied",
    )
    send_parser.add_argument("--actor", default="cli_send", help="Actor name for audit events")
    send_parser.add_argument(
        "--force",
        action="store_true",
        help="Allow an explicit resend of a non-pending request",
    )
    send_parser.add_argument("--reason", help="Required with --force")
    send_parser.set_defaults(func=handle_send)

    send_one_parser = subparsers.add_parser(
        "send-one",
        help="Queue and immediately send one review SMS using guest_name and guest_phone",
    )
    send_one_parser.add_argument("guest_name", help="Guest display name")
    send_one_parser.add_argument("guest_phone", help="Guest phone number, 04.. or E.164")
    send_one_parser.add_argument("--booking-ref", help="Optional metadata only")
    send_one_parser.add_argument("--booking-id", help="Future comms/nerve booking id")
    send_one_parser.add_argument("--stay-id", help="Future comms/nerve stay id")
    send_one_parser.add_argument("--guest-id", help="Future comms/nerve guest id")
    send_one_parser.add_argument("--property-id", help="Future comms/nerve property id")
    send_one_parser.add_argument("--unit-id", help="Future comms/nerve unit id")
    send_one_parser.add_argument("--check-in-date", help="Optional metadata only")
    send_one_parser.add_argument("--check-out-date", help="Optional metadata only")
    send_one_parser.add_argument(
        "--rule-key",
        default=DEFAULT_RULE_KEY,
        help=f"Automation rule key to record (default: {DEFAULT_RULE_KEY})",
    )
    send_one_parser.add_argument(
        "--channel",
        choices=("sms",),
        default="sms",
        help="Channel to record for future comms compatibility (default: sms)",
    )
    send_one_parser.add_argument(
        "--template-key",
        default=DEFAULT_TEMPLATE_KEY,
        help=f"Template key to record (default: {DEFAULT_TEMPLATE_KEY})",
    )
    send_one_parser.add_argument(
        "--template-path",
        help=f"Template file path (default: {DEFAULT_TEMPLATE_PATH})",
    )
    send_one_parser.add_argument("--message-body", help="Override the default Jim template")
    send_one_parser.add_argument("--actor", default="cli_send_one", help="Actor name for audit events")
    send_one_parser.add_argument(
        "--force",
        action="store_true",
        help="Allow an explicit resend when the ledger says this message already went out",
    )
    send_one_parser.add_argument("--reason", help="Required with --force")
    send_one_parser.set_defaults(func=handle_send_one)

    send_raw_parser = subparsers.add_parser(
        "send-raw",
        help="Parse one raw string containing a guest name and phone, then send immediately",
    )
    send_raw_parser.add_argument(
        "raw_input",
        nargs="*",
        help="Raw input like 'Min 0425287828' or '0425287828 Min'",
    )
    send_raw_parser.add_argument("--booking-ref", help="Optional metadata only")
    send_raw_parser.add_argument("--booking-id", help="Future comms/nerve booking id")
    send_raw_parser.add_argument("--stay-id", help="Future comms/nerve stay id")
    send_raw_parser.add_argument("--guest-id", help="Future comms/nerve guest id")
    send_raw_parser.add_argument("--property-id", help="Future comms/nerve property id")
    send_raw_parser.add_argument("--unit-id", help="Future comms/nerve unit id")
    send_raw_parser.add_argument("--check-in-date", help="Optional metadata only")
    send_raw_parser.add_argument("--check-out-date", help="Optional metadata only")
    send_raw_parser.add_argument(
        "--rule-key",
        default=DEFAULT_RULE_KEY,
        help=f"Automation rule key to record (default: {DEFAULT_RULE_KEY})",
    )
    send_raw_parser.add_argument(
        "--channel",
        choices=("sms",),
        default="sms",
        help="Channel to record for future comms compatibility (default: sms)",
    )
    send_raw_parser.add_argument(
        "--template-key",
        default=DEFAULT_TEMPLATE_KEY,
        help=f"Template key to record (default: {DEFAULT_TEMPLATE_KEY})",
    )
    send_raw_parser.add_argument(
        "--template-path",
        help=f"Template file path (default: {DEFAULT_TEMPLATE_PATH})",
    )
    send_raw_parser.add_argument("--message-body", help="Override the default Jim template")
    send_raw_parser.add_argument("--actor", default="cli_send_raw", help="Actor name for audit events")
    send_raw_parser.add_argument(
        "--force",
        action="store_true",
        help="Allow an explicit resend when the ledger says this message already went out",
    )
    send_raw_parser.add_argument("--reason", help="Required with --force")
    send_raw_parser.set_defaults(func=handle_send_raw)

    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    argv = list(argv) if argv is not None else sys.argv[1:]
    known_commands = {
        "prepare",
        "export",
        "mark-sent",
        "mark-failed",
        "list",
        "send",
        "send-one",
        "send-raw",
    }
    if argv and argv[0] not in known_commands and not argv[0].startswith("-"):
        argv = ["send-raw", *argv]

    parser = build_parser()
    args = parser.parse_args(argv)

    if getattr(args, "force", False) and not compact(getattr(args, "reason", "")):
        parser.error("--reason is required when --force is used")

    try:
        return args.func(args)
    except Exception as exc:
        LOGGER.error("Guest review request command failed: %s", exc)
        print(json.dumps({"error": str(exc)}, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
