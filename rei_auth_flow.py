#!/usr/bin/env python3
"""Shared REI login helpers, including authenticator-app verification handling."""

import logging
import time

from rei_credentials import get_rei_login_credentials, get_rei_totp


LOGIN_URL_HINTS = ("b2clogin", "/login", "/account")
MFA_URL_HINTS = ("mfa", "multifactor", "verification", "verify", "totp", "otp")
LOGIN_ERROR_SELECTORS = [
    ".error.itemLevel",
    ".error.pageLevel",
    "#error",
    ".error-message",
    "[aria-live='polite'].error",
    "[role='alert']",
]
MFA_EXPLICIT_INPUT_SELECTORS = [
    "input#otpCode",
    "input#verificationCode",
    "input#verificationcode",
    "input#otp",
    "input#totp",
    "input[name='verificationCode']",
    "input[name='verificationcode']",
    "input[name='otp']",
    "input[name='totp']",
    "input[name='otc']",
    "input[autocomplete='one-time-code']",
]
MFA_FALLBACK_INPUT_SELECTORS = [
    "input[inputmode='numeric']",
]
MFA_SUBMIT_SELECTORS = [
    "button#continue",
    "button#next",
    "button[type='submit']",
    "input[type='submit']",
    "button:has-text('Verify')",
    "button:has-text('Continue')",
    "button:has-text('Next')",
    "button:has-text('Sign in')",
]
MFA_TEXT_HINTS = (
    "verification code",
    "authenticator app",
    "one-time password",
    "security code",
    "two-factor",
    "two factor",
    "multi-factor",
    "mfa",
    "totp",
    "otp",
)
MFA_DUPLICATE_CODE_TEXT = "duplicate verification code"
MFA_CODE_REFRESH_TIMEOUT_SECONDS = 35
MFA_CODE_REFRESH_POLL_SECONDS = 1


def _get_logger(logger=None):
    return logger or logging.getLogger(__name__)


def locator_is_visible(target_page, selector):
    try:
        locator = target_page.locator(selector)
        if locator.count() == 0:
            return False
        return locator.first.is_visible()
    except Exception:
        return False


def _first_visible_selector(target_page, selectors):
    for selector in selectors:
        if locator_is_visible(target_page, selector):
            return selector
    return ""


def get_visible_auth_error_text(target_page):
    for selector in LOGIN_ERROR_SELECTORS:
        try:
            error_elem = target_page.locator(selector)
            if error_elem.count() == 0 or not error_elem.first.is_visible():
                continue
            error_text = (error_elem.first.text_content() or "").strip()
            if error_text:
                return error_text
        except Exception:
            continue
    return ""


def page_requires_totp(target_page):
    if not target_page:
        return False

    explicit_selector = _first_visible_selector(target_page, MFA_EXPLICIT_INPUT_SELECTORS)
    if explicit_selector:
        return True

    fallback_selector = _first_visible_selector(target_page, MFA_FALLBACK_INPUT_SELECTORS)
    if not fallback_selector:
        return False

    try:
        current_url = target_page.url.lower()
    except Exception:
        current_url = ""

    try:
        content = (target_page.content() or "").lower()
    except Exception:
        content = ""

    return any(hint in current_url or hint in content for hint in MFA_URL_HINTS + MFA_TEXT_HINTS)


def page_is_login_page(target_page):
    if not target_page:
        return True

    if page_requires_totp(target_page):
        return False

    try:
        current_url = target_page.url.lower()
    except Exception:
        current_url = ""

    if locator_is_visible(target_page, "input#email") and locator_is_visible(target_page, "input#password"):
        return True

    if any(hint in current_url for hint in LOGIN_URL_HINTS):
        return True

    try:
        content = (target_page.content() or "").lower()
    except Exception:
        content = ""

    return "member login" in content or ("password" in content and "email address" in content)


def wait_for_new_totp_code(
    previous_code,
    *,
    logger=None,
    get_totp=None,
    timeout_seconds=MFA_CODE_REFRESH_TIMEOUT_SECONDS,
    poll_seconds=MFA_CODE_REFRESH_POLL_SECONDS,
):
    log = _get_logger(logger)
    get_totp = get_totp or (lambda: get_rei_totp(logger=log))

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        next_code = get_totp()
        if next_code and next_code != previous_code:
            return next_code
        time.sleep(poll_seconds)

    log.warning("Timed out waiting for a fresh authenticator code.")
    return ""


def complete_totp_verification(target_page, logger=None, get_totp=None):
    log = _get_logger(logger)
    get_totp = get_totp or (lambda: get_rei_totp(logger=log))

    verification_code = get_totp()
    if not verification_code:
        log.error(
            "Authenticator app verification is required, but no TOTP source is configured. "
            "Set REI_TOTP or configure 1Password."
        )
        return ""

    input_selector = _first_visible_selector(
        target_page,
        MFA_EXPLICIT_INPUT_SELECTORS + MFA_FALLBACK_INPUT_SELECTORS,
    )
    if not input_selector:
        log.error("Authenticator app verification is required, but no verification code field was found.")
        return ""

    log.info("  -> Filling authenticator app verification code...")
    try:
        target_page.locator(input_selector).first.fill(verification_code)
        target_page.wait_for_timeout(300)
    except Exception as exc:
        log.error("Could not fill verification code field: %s", exc)
        return ""

    submit_selector = _first_visible_selector(target_page, MFA_SUBMIT_SELECTORS)
    if submit_selector:
        log.info("  -> Submitting authenticator app verification...")
        try:
            target_page.locator(submit_selector).first.click()
            return verification_code
        except Exception as exc:
            log.error("Could not submit authenticator app verification: %s", exc)
            return ""

    try:
        target_page.locator(input_selector).first.press("Enter")
        return verification_code
    except Exception as exc:
        log.error("Could not submit verification code with Enter: %s", exc)
        return ""


def auto_login(
    target_page,
    *,
    is_authenticated_session,
    logger=None,
    max_attempts=3,
    get_username=None,
    get_password=None,
    get_totp=None,
):
    log = _get_logger(logger)

    if get_username is None or get_password is None:
        default_username, default_password = get_rei_login_credentials(logger=log)
        get_username = get_username or (lambda: default_username)
        get_password = get_password or (lambda: default_password)

    username = get_username()
    password = get_password()

    if not username or not password:
        log.info("No REI credentials configured - manual login required")
        return False

    log.info("Attempting auto-login to REI Cloud...")

    for attempt in range(1, max_attempts + 1):
        try:
            submitted_code = ""
            log.info("  Login attempt %s/%s...", attempt, max_attempts)
            target_page.wait_for_timeout(3000)

            if is_authenticated_session(target_page):
                log.info("Already logged in.")
                return True

            if page_requires_totp(target_page):
                log.info("  -> Authenticator app verification required...")
                submitted_code = complete_totp_verification(target_page, logger=log, get_totp=get_totp)
                if not submitted_code:
                    return False
                log.info("  -> Waiting for verification response...")
                target_page.wait_for_timeout(8000)
                if is_authenticated_session(target_page):
                    log.info("Auto-login successful.")
                    return True

                error_text = get_visible_auth_error_text(target_page)
                if error_text:
                    if MFA_DUPLICATE_CODE_TEXT in error_text.lower() and attempt < max_attempts:
                        log.warning("Verification code was reused. Waiting for a fresh authenticator code before retrying...")
                        wait_for_new_totp_code(submitted_code, logger=log, get_totp=get_totp)
                        continue
                    log.error("Verification failed - error shown: %s", error_text)
                    return False

                if attempt < max_attempts:
                    wait_for_new_totp_code(submitted_code, logger=log, get_totp=get_totp)
                    log.info("  Verification state not yet confirmed, will retry...")
                    continue
                return False

            if not page_is_login_page(target_page):
                log.info("Not on login page, but protected state is not yet verified.")
                if attempt < max_attempts:
                    continue
                return False

            log.info("  -> Waiting for login form...")
            try:
                target_page.wait_for_selector("input#email", state="visible", timeout=10000)
            except Exception as exc:
                log.error("Login form did not appear: %s", exc)
                if attempt < max_attempts:
                    continue
                return False

            log.info("  -> Filling in email...")
            try:
                target_page.locator("input#email").first.fill(username)
                target_page.wait_for_timeout(500)
            except Exception as exc:
                log.error("Could not fill email field: %s", exc)
                return False

            log.info("  -> Filling in password...")
            try:
                target_page.locator("input#password").first.fill(password)
                target_page.wait_for_timeout(500)
            except Exception as exc:
                log.error("Could not fill password field: %s", exc)
                return False

            log.info("  -> Clicking 'Sign in' button...")
            try:
                target_page.locator("button#next").first.click()
            except Exception as exc:
                log.error("Could not click submit button: %s", exc)
                return False

            log.info("  -> Waiting for response...")
            target_page.wait_for_timeout(10000)

            if page_requires_totp(target_page):
                log.info("  -> Authenticator app verification required...")
                submitted_code = complete_totp_verification(target_page, logger=log, get_totp=get_totp)
                if not submitted_code:
                    return False
                log.info("  -> Waiting for verification response...")
                target_page.wait_for_timeout(8000)

            if is_authenticated_session(target_page):
                log.info("Auto-login successful.")
                return True

            error_text = get_visible_auth_error_text(target_page)
            if error_text:
                if MFA_DUPLICATE_CODE_TEXT in error_text.lower() and attempt < max_attempts:
                    log.warning("Verification code was reused. Waiting for a fresh authenticator code before retrying...")
                    wait_for_new_totp_code(submitted_code, logger=log, get_totp=get_totp)
                    continue
                log.error("Login failed - error shown: %s", error_text)
                return False

            if page_requires_totp(target_page):
                if attempt < max_attempts:
                    wait_for_new_totp_code(submitted_code, logger=log, get_totp=get_totp)
                    log.info("  Verification state not yet confirmed, will retry...")
                    continue
                return False

            if page_is_login_page(target_page):
                log.info("  Still on login page, will retry...")
                continue

            if attempt < max_attempts:
                log.info("  Login state not yet verified, will retry...")
                continue
            return False
        except Exception as exc:
            log.error("Auto-login attempt %s error: %s", attempt, exc)
            if attempt >= max_attempts:
                return False

    log.warning("Auto-login: max attempts reached, still not authenticated")
    return False
