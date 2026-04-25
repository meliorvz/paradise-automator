#!/usr/bin/env python3
"""
Outbound communications clients for Paradise Automator.

The existing Comms Centre integration remains available as fallback. Resend is
the default report email provider, Brrr handles urgent alerts, and ntfy handles
lightweight operational notifications.
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

DEFAULT_BRRR_SEND_URL = "https://api.brrr.now/v1/send"
DEFAULT_NTFY_BASE_URL = "https://ntfy.sh"
DEFAULT_RESEND_API_URL = "https://api.resend.com/emails"
DEFAULT_RESEND_FROM = "Paradise Stayz Updates <reports@updates.paradisestayz.com.au>"


@dataclass
class SendResult:
    success: bool
    status_code: int | None = None
    response_json: dict[str, Any] | None = None
    response_text: str = ""
    response_headers: dict[str, str] | None = None
    error: str | None = None


@dataclass(frozen=True)
class ResendEmailConfig:
    api_url: str
    api_key: str
    from_email: str
    reply_to: str = ""

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key.strip())

    @property
    def has_sender(self) -> bool:
        return bool(self.from_email.strip())

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }


@dataclass(frozen=True)
class BrrrAlertConfig:
    webhook_url: str
    webhook_secret: str
    method: str
    title_prefix: str
    thread_id: str
    interruption_level: str
    sound: str
    open_url: str

    @property
    def has_destination(self) -> bool:
        return bool(self.webhook_url.strip() or self.webhook_secret.strip())

    @property
    def resolved_url(self) -> str:
        return self.webhook_url.strip() or DEFAULT_BRRR_SEND_URL

    @property
    def headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.webhook_secret.strip():
            headers["Authorization"] = f"Bearer {self.webhook_secret.strip()}"
        return headers


@dataclass(frozen=True)
class NtfyAlertConfig:
    base_url: str
    topic: str
    username: str
    password: str
    token: str
    title_prefix: str
    priority: str
    tags: str
    click_url: str
    cache: str

    @property
    def has_destination(self) -> bool:
        return bool(self.topic.strip())

    @property
    def resolved_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/{self.topic.lstrip('/')}"

    @property
    def headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.token.strip():
            headers["Authorization"] = f"Bearer {self.token.strip()}"
        if self.tags.strip():
            headers["Tags"] = self.tags.strip()
        if self.click_url.strip():
            headers["Click"] = self.click_url.strip()
        if self.cache.strip():
            headers["Cache"] = self.cache.strip()
        return headers

    @property
    def basic_auth(self) -> tuple[str, str] | None:
        if self.token.strip():
            return None
        if self.username.strip() and self.password:
            return (self.username.strip(), self.password)
        return None


class ResendEmailClient:
    """HTTP client for Resend's email API."""

    def __init__(self, config: ResendEmailConfig) -> None:
        self.config = config

    def send_email(
        self,
        *,
        subject: str,
        text: str,
        html: str,
        to: list[str],
        cc: list[str] | None = None,
        attachments: list[dict[str, str]] | None = None,
        timeout: int = 60,
        retry_total: int = 3,
    ) -> SendResult:
        if not self.config.has_api_key:
            return SendResult(success=False, error="RESEND_API_KEY is not configured")
        if not self.config.has_sender:
            return SendResult(success=False, error="RESEND_FROM is not configured")
        if not to:
            return SendResult(success=False, error="No email recipients provided")

        payload: dict[str, Any] = {
            "from": self.config.from_email,
            "to": to,
            "subject": subject,
            "text": text,
            "html": html,
        }
        if cc:
            payload["cc"] = cc
        if self.config.reply_to:
            payload["reply_to"] = self.config.reply_to
        if attachments:
            payload["attachments"] = attachments

        session = requests.Session()
        if retry_total > 0:
            retry = Retry(
                total=retry_total,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["POST"],
            )
            adapter = HTTPAdapter(max_retries=retry)
            session.mount("https://", adapter)
            session.mount("http://", adapter)

        try:
            headers = dict(self.config.headers)
            headers["Idempotency-Key"] = f"paradise-automator-{uuid.uuid4()}"
            response = session.post(
                self.config.api_url,
                json=payload,
                headers=headers,
                timeout=timeout,
            )
            response_json = None
            try:
                response_json = response.json()
            except Exception:
                response_json = None
            success = bool(
                response.status_code in {200, 201, 202}
                and isinstance(response_json, dict)
                and response_json.get("id")
            )
            return SendResult(
                success=success,
                status_code=response.status_code,
                response_json=response_json if isinstance(response_json, dict) else None,
                response_text=response.text,
                response_headers=dict(response.headers),
            )
        except Exception as exc:
            return SendResult(success=False, error=str(exc))
        finally:
            session.close()


class BrrrAlertClient:
    """Webhook client for Brrr push notifications."""

    def __init__(self, config: BrrrAlertConfig) -> None:
        self.config = config

    def send_alert(
        self,
        *,
        title: str,
        body: str,
        severity: str = "error",
        timeout: int = 30,
    ) -> SendResult:
        if not self.config.has_destination:
            return SendResult(success=False, error="BRRR_WEBHOOK_URL or BRRR_WEBHOOK_SECRET is not configured")

        title_with_prefix = f"{self.config.title_prefix}{title}" if self.config.title_prefix else title
        payload: dict[str, Any] = {
            "title": title_with_prefix,
            "message": body,
            "severity": severity,
        }
        if self.config.thread_id:
            payload["thread_id"] = self.config.thread_id
        if self.config.interruption_level:
            payload["interruption_level"] = self.config.interruption_level
        if self.config.sound:
            payload["sound"] = self.config.sound
        if self.config.open_url:
            payload["open_url"] = self.config.open_url

        session = requests.Session()
        try:
            method = self.config.method.upper()
            if method == "GET":
                response = session.get(
                    self.config.resolved_url,
                    params=payload,
                    headers=self.config.headers if self.config.webhook_secret else None,
                    timeout=timeout,
                )
            else:
                response = session.post(
                    self.config.resolved_url,
                    json=payload,
                    headers=self.config.headers,
                    timeout=timeout,
                )

            response_json = None
            try:
                response_json = response.json()
            except Exception:
                response_json = None
            return SendResult(
                success=200 <= response.status_code < 300,
                status_code=response.status_code,
                response_json=response_json if isinstance(response_json, dict) else None,
                response_text=response.text,
                response_headers=dict(response.headers),
            )
        except Exception as exc:
            return SendResult(success=False, error=str(exc))
        finally:
            session.close()


class NtfyAlertClient:
    """HTTP client for ntfy push notifications."""

    def __init__(self, config: NtfyAlertConfig) -> None:
        self.config = config

    def _resolve_priority(self, severity: str) -> str:
        if self.config.priority.strip():
            return self.config.priority.strip()

        severity_map = {
            "critical": "5",
            "error": "5",
            "warning": "4",
            "warn": "4",
            "info": "3",
            "default": "3",
        }
        return severity_map.get((severity or "").strip().lower(), "3")

    def send_alert(
        self,
        *,
        title: str,
        body: str,
        severity: str = "error",
        timeout: int = 30,
    ) -> SendResult:
        if not self.config.has_destination:
            return SendResult(success=False, error="NTFY_TOPIC is not configured")

        headers = dict(self.config.headers)
        title_with_prefix = f"{self.config.title_prefix}{title}" if self.config.title_prefix else title
        headers["Title"] = title_with_prefix
        headers["Priority"] = self._resolve_priority(severity)

        session = requests.Session()
        try:
            response = session.post(
                self.config.resolved_url,
                data=body,
                headers=headers,
                auth=self.config.basic_auth,
                timeout=timeout,
            )
            response_json = None
            try:
                response_json = response.json()
            except Exception:
                response_json = None
            return SendResult(
                success=200 <= response.status_code < 300,
                status_code=response.status_code,
                response_json=response_json if isinstance(response_json, dict) else None,
                response_text=response.text,
                response_headers=dict(response.headers),
            )
        except Exception as exc:
            return SendResult(success=False, error=str(exc))
        finally:
            session.close()


def resolve_resend_email_config() -> ResendEmailConfig:
    return ResendEmailConfig(
        api_url=(os.getenv("RESEND_API_URL", DEFAULT_RESEND_API_URL) or DEFAULT_RESEND_API_URL).strip(),
        api_key=(os.getenv("RESEND_API_KEY", "") or "").strip(),
        from_email=(os.getenv("RESEND_FROM", DEFAULT_RESEND_FROM) or DEFAULT_RESEND_FROM).strip(),
        reply_to=(os.getenv("RESEND_REPLY_TO", "") or "").strip(),
    )


def build_resend_email_client() -> ResendEmailClient:
    return ResendEmailClient(resolve_resend_email_config())


def resolve_ntfy_alert_config() -> NtfyAlertConfig:
    return NtfyAlertConfig(
        base_url=(os.getenv("NTFY_BASE_URL", DEFAULT_NTFY_BASE_URL) or DEFAULT_NTFY_BASE_URL).strip(),
        topic=(os.getenv("NTFY_TOPIC", "") or "").strip(),
        username=(os.getenv("NTFY_USERNAME", "") or "").strip(),
        password=os.getenv("NTFY_PASSWORD", "") or "",
        token=(os.getenv("NTFY_TOKEN", "") or "").strip(),
        title_prefix=(os.getenv("NTFY_ALERT_TITLE_PREFIX", "[Paradise] ") or "").strip(),
        priority=(os.getenv("NTFY_ALERT_PRIORITY", "") or "").strip(),
        tags=(os.getenv("NTFY_ALERT_TAGS", "paradise-automator") or "").strip(),
        click_url=(os.getenv("NTFY_ALERT_CLICK_URL", "") or "").strip(),
        cache=(os.getenv("NTFY_ALERT_CACHE", "") or "").strip(),
    )


def build_ntfy_alert_client() -> NtfyAlertClient:
    return NtfyAlertClient(resolve_ntfy_alert_config())


def resolve_brrr_alert_config() -> BrrrAlertConfig:
    method = (os.getenv("BRRR_WEBHOOK_METHOD", "POST") or "POST").strip().upper()
    if method not in {"POST", "GET"}:
        logger.warning("Unknown BRRR_WEBHOOK_METHOD '%s'. Falling back to POST.", method)
        method = "POST"

    title_prefix = os.getenv("BRRR_ALERT_TITLE_PREFIX", "[Paradise] ") or ""
    return BrrrAlertConfig(
        webhook_url=(os.getenv("BRRR_WEBHOOK_URL", "") or "").strip(),
        webhook_secret=(os.getenv("BRRR_WEBHOOK_SECRET", "") or "").strip(),
        method=method,
        title_prefix=title_prefix,
        thread_id=(os.getenv("BRRR_ALERT_THREAD_ID", "paradise-automator") or "").strip(),
        interruption_level=(os.getenv("BRRR_ALERT_INTERRUPTION_LEVEL", "time-sensitive") or "").strip(),
        sound=(os.getenv("BRRR_ALERT_SOUND", "") or "").strip(),
        open_url=(os.getenv("BRRR_ALERT_OPEN_URL", "") or "").strip(),
    )


def build_brrr_alert_client() -> BrrrAlertClient:
    return BrrrAlertClient(resolve_brrr_alert_config())
