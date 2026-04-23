#!/usr/bin/env python3
"""Resolve REI credentials from plain env vars or 1Password secret references."""

import logging
import os
import shutil
import subprocess


DEFAULT_1PASSWORD_VAULT = "paradise-automator-prod"
DEFAULT_1PASSWORD_ITEM = "paradise-automator-prod"
DEFAULT_1PASSWORD_USERNAME_FIELD = "username"
DEFAULT_1PASSWORD_PASSWORD_FIELD = "password"
DEFAULT_1PASSWORD_TOTP_FIELD = "otp"
FALLBACK_1PASSWORD_TOTP_FIELDS = ("one-time password",)
SECRET_REFERENCE_PREFIX = "op://"
OP_READ_TIMEOUT_SECONDS = 15


def _get_logger(logger=None):
    return logger or logging.getLogger(__name__)


def _config_value(name):
    return (os.getenv(name, "") or "").strip()


def _secret_value(name):
    value = os.getenv(name)
    if value is None:
        return ""
    return value


def _is_secret_reference(value):
    return value.lower().startswith(SECRET_REFERENCE_PREFIX)


def _onepassword_defaults_configured():
    return any(
        _config_value(name)
        for name in ("OP_SERVICE_ACCOUNT_TOKEN", "REI_1PASSWORD_VAULT", "REI_1PASSWORD_ITEM")
    )


def _build_secret_reference(field_name, attribute=None):
    vault_name = _config_value("REI_1PASSWORD_VAULT") or DEFAULT_1PASSWORD_VAULT
    item_name = _config_value("REI_1PASSWORD_ITEM") or DEFAULT_1PASSWORD_ITEM
    if not field_name or not vault_name or not item_name:
        return ""

    reference = f"op://{vault_name}/{item_name}/{field_name}"
    if attribute:
        reference = f"{reference}?attribute={attribute}"
    return reference


def _read_secret_reference(secret_reference, label, logger=None, log_errors=True):
    log = _get_logger(logger)

    if not shutil.which("op"):
        if log_errors:
            log.error(
                "1Password CLI is required to resolve %s, but `op` is not installed or not on PATH.",
                label,
            )
        return ""

    try:
        result = subprocess.run(
            ["op", "read", secret_reference],
            capture_output=True,
            text=True,
            timeout=OP_READ_TIMEOUT_SECONDS,
            check=False,
        )
    except Exception as exc:
        if log_errors:
            log.error("Failed to resolve %s from 1Password: %s", label, exc)
        return ""

    if result.returncode != 0:
        stderr = (result.stderr or "").strip() or "unknown 1Password CLI error"
        if log_errors:
            log.error("Failed to resolve %s from 1Password: %s", label, stderr)
        return ""

    return (result.stdout or "").rstrip("\r\n")


def _resolve_secret(
    env_name,
    *,
    default_field,
    field_env_name,
    attribute=None,
    logger=None,
):
    raw_value = _secret_value(env_name)
    trimmed_value = raw_value.strip() if raw_value else ""

    if trimmed_value:
        if _is_secret_reference(trimmed_value):
            return _read_secret_reference(trimmed_value, env_name, logger=logger)
        return raw_value

    if not _onepassword_defaults_configured():
        return ""

    field_name = _config_value(field_env_name) or default_field
    secret_reference = _build_secret_reference(field_name, attribute=attribute)
    if not secret_reference:
        return ""

    return _read_secret_reference(secret_reference, env_name, logger=logger)


def get_rei_username(logger=None):
    return _resolve_secret(
        "REI_USERNAME",
        default_field=DEFAULT_1PASSWORD_USERNAME_FIELD,
        field_env_name="REI_1PASSWORD_USERNAME_FIELD",
        logger=logger,
    )


def get_rei_password(logger=None):
    return _resolve_secret(
        "REI_PASSWORD",
        default_field=DEFAULT_1PASSWORD_PASSWORD_FIELD,
        field_env_name="REI_1PASSWORD_PASSWORD_FIELD",
        logger=logger,
    )


def get_rei_totp(logger=None):
    raw_value = _secret_value("REI_TOTP")
    trimmed_value = raw_value.strip() if raw_value else ""

    if trimmed_value:
        if _is_secret_reference(trimmed_value):
            totp = _read_secret_reference(trimmed_value, "REI_TOTP", logger=logger)
            if totp:
                return totp
        else:
            return raw_value

    if not _onepassword_defaults_configured():
        return ""

    configured_field = _config_value("REI_1PASSWORD_TOTP_FIELD") or DEFAULT_1PASSWORD_TOTP_FIELD
    secret_reference = _build_secret_reference(configured_field, attribute="otp")
    totp = _read_secret_reference(secret_reference, "REI_TOTP", logger=logger, log_errors=False)
    if totp:
        return totp

    for field_name in FALLBACK_1PASSWORD_TOTP_FIELDS:
        if field_name == configured_field:
            continue
        secret_reference = _build_secret_reference(field_name, attribute="otp")
        totp = _read_secret_reference(secret_reference, "REI_TOTP", logger=logger, log_errors=False)
        if totp:
            return totp

    _get_logger(logger).error(
        "Failed to resolve REI_TOTP from 1Password using configured or fallback TOTP fields."
    )
    return ""


def get_rei_login_credentials(logger=None):
    return get_rei_username(logger=logger), get_rei_password(logger=logger)
