#!/usr/bin/env python3
"""
Internal Comms transport adapter.

This keeps paradise-automator's outbound contract stable while allowing
provider selection by configuration for staged migration.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

DEFAULT_COMMS_API_URL = "https://comms-centre-prod.ancient-fire-eaa9.workers.dev/api/integrations/v1/send"
DEFAULT_COMMS_PROVIDER = "integration_api"
SUPPORTED_PROVIDER_ALIASES = {"integration_api", "vps_comms", "nerve_proxy"}


@dataclass(frozen=True)
class CommsClientConfig:
    provider: str
    api_url: str
    api_key: str

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key.strip())

    @property
    def headers(self) -> dict[str, str]:
        return {
            "x-integration-key": self.api_key,
            "Content-Type": "application/json",
        }


@dataclass
class CommsSendResult:
    success: bool
    status_code: int | None = None
    response_json: dict[str, Any] | None = None
    response_text: str = ""
    response_headers: dict[str, str] | None = None
    error: str | None = None


class IntegrationApiCommsClient:
    """
    HTTP client for the /api/integrations/v1/send contract.

    `vps_comms` and `nerve_proxy` providers intentionally use this same shape
    so current callers can switch by config only.
    """

    def __init__(self, config: CommsClientConfig) -> None:
        self.config = config

    def send(self, payload: dict[str, Any], timeout: int = 30, retry_total: int = 0) -> CommsSendResult:
        if not self.config.has_api_key:
            return CommsSendResult(success=False, error="COMMS_API_KEY is not configured")

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
            response = session.post(
                self.config.api_url,
                json=payload,
                headers=self.config.headers,
                timeout=timeout,
            )
            response_json = None
            try:
                response_json = response.json()
            except Exception:
                response_json = None
            success = bool(response.status_code == 200 and isinstance(response_json, dict) and response_json.get("success"))
            return CommsSendResult(
                success=success,
                status_code=response.status_code,
                response_json=response_json if isinstance(response_json, dict) else None,
                response_text=response.text,
                response_headers=dict(response.headers),
            )
        except Exception as exc:
            return CommsSendResult(success=False, error=str(exc))
        finally:
            session.close()


def resolve_comms_client_config() -> CommsClientConfig:
    provider = (os.getenv("COMMS_PROVIDER", DEFAULT_COMMS_PROVIDER) or DEFAULT_COMMS_PROVIDER).strip().lower()
    if provider not in SUPPORTED_PROVIDER_ALIASES:
        logger.warning(
            "Unknown COMMS_PROVIDER '%s'. Falling back to '%s'.",
            provider,
            DEFAULT_COMMS_PROVIDER,
        )
        provider = DEFAULT_COMMS_PROVIDER

    api_url = (os.getenv("COMMS_API_URL", DEFAULT_COMMS_API_URL) or DEFAULT_COMMS_API_URL).strip()
    api_key = (os.getenv("COMMS_API_KEY", "") or "").strip()
    return CommsClientConfig(provider=provider, api_url=api_url, api_key=api_key)


def build_comms_client() -> IntegrationApiCommsClient:
    return IntegrationApiCommsClient(resolve_comms_client_config())
