#!/usr/bin/env python3
"""
REI Cloud Automation - Simplified Version
Opens browser, lets you login and navigate, records URLs you visit.

Usage:
    ./run.sh --record    # Record your workflow
    ./run.sh --test      # Run automation every 5 minutes
    ./run.sh             # Run automation daily at 8 AM
"""

import os
import sys
import logging
import time
import signal
import threading
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytz
import schedule
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

load_dotenv()

# Configuration
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "./downloads"))
REI_CLOUD_URL = "https://reimasterapps.com.au/Customers/Dashboard?reicid=758"

# REI Cloud Credentials (optional - for auto-login)
REI_USERNAME = os.getenv("REI_USERNAME", "")
REI_PASSWORD = os.getenv("REI_PASSWORD", "")

DOWNLOAD_DIR.mkdir(exist_ok=True)

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("automation.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Import new booking extractor
try:
    from booking_data_extractor import run_daily_maintenance as run_booking_maintenance, run_historical as run_booking_historical
except ImportError:
    logger.warning("Could not import booking_data_extractor. Some features will be disabled.")
    def run_booking_maintenance(): logger.error("Booking extraction not implemented.")
    def run_booking_historical(): logger.error("Booking extraction not implemented.")

# Globals
playwright_instance = None
browser = None
context = None
page = None


def cleanup(signum=None, frame=None):
    """Clean shutdown."""
    logger.info("\nShutting down...")
    try:
        if context:
            context.close()
        if browser:
            browser.close()
        if playwright_instance:
            playwright_instance.stop()
    except:
        pass
    sys.exit(0)


# State File for tracking successful runs
STATE_FILE = "automation_state.json"

# Brisbane timezone for scheduling (handles AEST/AEDT automatically)
BRISBANE_TZ = pytz.timezone('Australia/Brisbane')

# Schedule configuration (in Brisbane local time)
# Daily at 13:00 Brisbane time (handles DST automatically)
SCHEDULED_RUN_HOUR = 13
SCHEDULED_RUN_MINUTE = 0
GRACE_PERIOD_MINUTES = 10

# Weekly schedule configuration (in Brisbane local time)
# Saturday at 08:00 Brisbane time (handles DST automatically)
WEEKLY_SCHEDULED_DAY = 5  # Saturday (Monday=0, Sunday=6)
WEEKLY_SCHEDULED_HOUR = 8
WEEKLY_SCHEDULED_MINUTE = 0
WEEKLY_GRACE_PERIOD_MINUTES = 10


def load_state():
    """Load the automation state."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return {}


def save_state(state):
    """Save the automation state."""
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save state: {e}")


def get_next_scheduled_time(from_time=None):
    """
    Calculate the next scheduled run time (tomorrow at SCHEDULED_RUN_HOUR:SCHEDULED_RUN_MINUTE Brisbane time).
    Returns ISO format string in UTC for storage.
    """
    # Use current time in Brisbane timezone
    if from_time is None:
        brisbane_now = datetime.now(BRISBANE_TZ)
    else:
        # Ensure from_time is timezone-aware in Brisbane
        if from_time.tzinfo is None:
            brisbane_now = BRISBANE_TZ.localize(from_time)
        else:
            brisbane_now = from_time.astimezone(BRISBANE_TZ)
    
    # Next run is tomorrow at the scheduled time (Brisbane time)
    tomorrow = brisbane_now.date() + timedelta(days=1)
    next_run_brisbane = BRISBANE_TZ.localize(datetime.combine(tomorrow, datetime.min.time().replace(
        hour=SCHEDULED_RUN_HOUR, minute=SCHEDULED_RUN_MINUTE
    )))
    
    # Convert to UTC for storage
    next_run_utc = next_run_brisbane.astimezone(pytz.UTC)
    return next_run_utc.isoformat()


def get_next_weekly_scheduled_time(from_time=None):
    """
    Calculate the next weekly scheduled run time (next Saturday at 08:00 Brisbane time).
    Returns ISO format string in UTC for storage.
    """
    # Use current time in Brisbane timezone
    if from_time is None:
        brisbane_now = datetime.now(BRISBANE_TZ)
    else:
        # Ensure from_time is timezone-aware in Brisbane
        if from_time.tzinfo is None:
            brisbane_now = BRISBANE_TZ.localize(from_time)
        else:
            brisbane_now = from_time.astimezone(BRISBANE_TZ)
    
    # Find days until next Saturday
    days_ahead = WEEKLY_SCHEDULED_DAY - brisbane_now.weekday()
    if days_ahead <= 0:  # Target day already passed this week
        days_ahead += 7
    
    next_saturday = brisbane_now.date() + timedelta(days=days_ahead)
    next_run_brisbane = BRISBANE_TZ.localize(datetime.combine(next_saturday, datetime.min.time().replace(
        hour=WEEKLY_SCHEDULED_HOUR, minute=WEEKLY_SCHEDULED_MINUTE
    )))
    
    # Convert to UTC for storage
    next_run_utc = next_run_brisbane.astimezone(pytz.UTC)
    return next_run_utc.isoformat()


def save_successful_run():
    """
    Record a successful run. Updates last_successful_run and calculates next_expected_run.
    Called after ANY successful run (scheduled or manual).
    """
    now = datetime.now(pytz.UTC)  # Store in UTC
    state = load_state()
    state["last_successful_run"] = now.isoformat()
    state["next_expected_run"] = get_next_scheduled_time(now)
    save_state(state)
    logger.info(f"State saved: last_successful_run={now.isoformat()}, next_expected_run={state['next_expected_run']}")


def save_successful_weekly_run():
    """
    Record a successful weekly run. Updates last_successful_weekly_run and 
    calculates next_expected_weekly_run. Called after ANY successful weekly run.
    """
    now = datetime.now(pytz.UTC)  # Store in UTC
    state = load_state()
    state["last_successful_weekly_run"] = now.isoformat()
    state["next_expected_weekly_run"] = get_next_weekly_scheduled_time(now)
    save_state(state)
    logger.info(f"Weekly state saved: last_successful_weekly_run={now.isoformat()}, next_expected_weekly_run={state['next_expected_weekly_run']}")


def init_state_if_needed():
    """
    Initialize state on startup if next_expected_run is missing.
    Also migrates legacy 'last_run_date' to new format.
    Sets next_expected_run to today's scheduled time if before that time,
    or tomorrow if after (all in Brisbane timezone).
    """
    state = load_state()
    
    # Migrate legacy state: convert last_run_date to last_successful_run
    if "last_run_date" in state and "last_successful_run" not in state:
        # Convert date string to full timestamp (assume it ran at scheduled time in Brisbane)
        try:
            old_date = datetime.strptime(state["last_run_date"], "%Y-%m-%d")
            migrated_time = BRISBANE_TZ.localize(old_date.replace(hour=SCHEDULED_RUN_HOUR, minute=SCHEDULED_RUN_MINUTE))
            state["last_successful_run"] = migrated_time.astimezone(pytz.UTC).isoformat()
            del state["last_run_date"]  # Remove legacy field
            logger.info(f"Migrated legacy state: last_run_date -> last_successful_run={state['last_successful_run']}")
        except Exception as e:
            logger.error(f"Failed to migrate legacy state: {e}")
    
    if "next_expected_run" not in state:
        # Use Brisbane timezone for scheduling logic
        brisbane_now = datetime.now(BRISBANE_TZ)
        today_scheduled = BRISBANE_TZ.localize(datetime.combine(brisbane_now.date(), datetime.min.time().replace(
            hour=SCHEDULED_RUN_HOUR, minute=SCHEDULED_RUN_MINUTE
        )))
        
        if brisbane_now < today_scheduled:
            # Before today's run time - set deadline to today (store in UTC)
            state["next_expected_run"] = today_scheduled.astimezone(pytz.UTC).isoformat()
        else:
            # After today's run time - set deadline to tomorrow
            state["next_expected_run"] = get_next_scheduled_time(brisbane_now)
        
        save_state(state)
        logger.info(f"Initialized state with next_expected_run={state['next_expected_run']}")
    
    return state


def init_weekly_state_if_needed():
    """
    Initialize weekly state on startup if next_expected_weekly_run is missing.
    Sets next_expected_weekly_run to this Saturday if before that time,
    or next Saturday if after (all in Brisbane timezone).
    """
    state = load_state()
    
    if "next_expected_weekly_run" not in state:
        # Use Brisbane timezone for scheduling logic
        brisbane_now = datetime.now(BRISBANE_TZ)
        
        # Calculate this Saturday
        days_until_saturday = WEEKLY_SCHEDULED_DAY - brisbane_now.weekday()
        if days_until_saturday < 0:  
            days_until_saturday += 7
        
        this_saturday = brisbane_now.date() + timedelta(days=days_until_saturday)
        this_saturday_scheduled = BRISBANE_TZ.localize(datetime.combine(this_saturday, datetime.min.time().replace(
            hour=WEEKLY_SCHEDULED_HOUR, minute=WEEKLY_SCHEDULED_MINUTE
        )))
        
        if brisbane_now < this_saturday_scheduled:
            # Before this Saturday's run time - set deadline to this Saturday (store in UTC)
            state["next_expected_weekly_run"] = this_saturday_scheduled.astimezone(pytz.UTC).isoformat()
        else:
            # After this Saturday's run time - set deadline to next Saturday
            state["next_expected_weekly_run"] = get_next_weekly_scheduled_time(brisbane_now)
        
        save_state(state)
        logger.info(f"Initialized weekly state with next_expected_weekly_run={state['next_expected_weekly_run']}")
    
    return state


def is_past_deadline():
    """
    Check if current time is past the deadline (next_expected_run + grace period).
    Returns (is_past, next_expected_run_dt, last_successful_run_dt)
    All comparisons done in UTC timezone.
    """
    state = load_state()
    next_run_str = state.get("next_expected_run")
    last_success_str = state.get("last_successful_run")
    
    if not next_run_str:
        return False, None, None
    
    try:
        next_run_dt = datetime.fromisoformat(next_run_str)
        # Ensure timezone-aware (assume UTC if no timezone)
        if next_run_dt.tzinfo is None:
            next_run_dt = pytz.UTC.localize(next_run_dt)
        deadline = next_run_dt + timedelta(minutes=GRACE_PERIOD_MINUTES)
        
        last_success_dt = None
        if last_success_str:
            last_success_dt = datetime.fromisoformat(last_success_str)
            if last_success_dt.tzinfo is None:
                last_success_dt = pytz.UTC.localize(last_success_dt)
        
        now = datetime.now(pytz.UTC)  # Use UTC for comparison
        is_past = now > deadline
        
        return is_past, next_run_dt, last_success_dt
    except Exception as e:
        logger.error(f"Error parsing state timestamps: {e}")
        return False, None, None


def is_past_weekly_deadline():
    """
    Check if current time is past the weekly deadline (next_expected_weekly_run + grace period).
    Returns (is_past, next_expected_run_dt, last_successful_run_dt)
    All comparisons done in UTC timezone.
    """
    state = load_state()
    next_run_str = state.get("next_expected_weekly_run")
    last_success_str = state.get("last_successful_weekly_run")
    
    if not next_run_str:
        return False, None, None
    
    try:
        next_run_dt = datetime.fromisoformat(next_run_str)
        # Ensure timezone-aware (assume UTC if no timezone)
        if next_run_dt.tzinfo is None:
            next_run_dt = pytz.UTC.localize(next_run_dt)
        deadline = next_run_dt + timedelta(minutes=WEEKLY_GRACE_PERIOD_MINUTES)
        
        last_success_dt = None
        if last_success_str:
            last_success_dt = datetime.fromisoformat(last_success_str)
            if last_success_dt.tzinfo is None:
                last_success_dt = pytz.UTC.localize(last_success_dt)
        
        now = datetime.now(pytz.UTC)  # Use UTC for comparison
        is_past = now > deadline
        
        return is_past, next_run_dt, last_success_dt
    except Exception as e:
        logger.error(f"Error parsing weekly state timestamps: {e}")
        return False, None, None


def configure_report_options(target_page):
    """
    Configure report modal options before preview.
    - Hides Account Balances
    - SHOWS Guest and Manager Comments (Disables 'Hide' toggles)
    """
    options = [
        ("hide_account_balances", True),   # We want to hide these
        ("hide_guest_comment", False),    # We want to SHOW these (uncheck hide)
        ("hide_manager_comments", False),  # We want to SHOW these (uncheck hide)
    ]
    
    for option_id, should_hide in options:
        try:
            checkbox = target_page.locator(f"#{option_id}")
            if checkbox.count() > 0:
                is_currently_hidden = checkbox.is_checked()
                
                if is_currently_hidden != should_hide:
                    # Click the Bootstrap switch wrapper to toggle it
                    switch_wrapper = target_page.locator(f".bootstrap-switch-id-{option_id}")
                    if switch_wrapper.count() > 0:
                        switch_wrapper.click()
                        status = "Enabled" if should_hide else "Disabled"
                        logger.info(f"  ✓ {status}: {option_id}")
                    else:
                        checkbox.click()
                        status = "Enabled" if should_hide else "Disabled"
                        logger.info(f"  ✓ {status} (fallback): {option_id}")
                else:
                    status = "already hidden" if should_hide else "already shown"
                    logger.info(f"  - {option_id} {status}")
            else:
                logger.warning(f"  Option not found: #{option_id}")
        except Exception as e:
            logger.warning(f"  Could not set #{option_id}: {e}")
    
    target_page.wait_for_timeout(500)


def run_daily_report():
    """Execute the daily report workflow: Arrivals and Departures for tomorrow."""
    global page, context
    
    logger.info("=" * 60)
    logger.info(f"RUNNING DAILY REPORT - {datetime.now()}")
    logger.info("=" * 60)
    
    try:
        # Go to Report List
        logger.info("Navigating to Report List...")
        page.goto("https://reimasterapps.com.au/report/reportlist?reicid=758", timeout=30000)
        page.wait_for_timeout(3000)
        
        # ===== ARRIVAL REPORT =====
        logger.info("Generating Arrival Report for tomorrow...")
        
        # Click on Arrival Report
        try:
            page.click("text=Arrival Report", timeout=5000)
        except:
            logger.info("Retry clicking Arrival Report...")
            page.goto("https://reimasterapps.com.au/report/reportlist?reicid=758")
            page.wait_for_timeout(3000)
            page.click("text=Arrival Report")
            
        page.wait_for_timeout(2000)
        
        # Configure hide options
        logger.info("Configuring report options (Hide toggles)...")
        configure_report_options(page)
        
        # Select Tomorrow in the popup
        logger.info("Selecting 'Tomorrow' for reports...")
        page.click("text=Tomorrow")
        page.wait_for_timeout(1000)
        
        # Click Preview button - this opens a new tab
        # Using exact ID found via inspection
        with context.expect_page() as new_page_info:
            page.click("a#btnPreviewBookingDate")
        report_page = new_page_info.value
        report_page.wait_for_load_state("networkidle")
        logger.info("Report preview opened in new tab")
        
        # Click the save/export dropdown (the download icon)
        report_page.wait_for_timeout(2000)
        
        # Click the export dropdown button
        # There are often two (top/bottom), find the visible one
        try:
            export_btns = report_page.locator("[title='Export']")
            count = export_btns.count()
            export_clicked = False
            
            for i in range(count):
                if export_btns.nth(i).is_visible():
                    logger.info("Found visible export button, clicking...")
                    export_btns.nth(i).click()
                    export_clicked = True
                    break
            
            if not export_clicked:
                logger.warning("No visible export button found, attempting force click on first...")
                export_btns.first.click(force=True)
                
        except Exception as e:
            logger.error(f"Error clicking export button: {e}")
            # Try specific ID as fallback
            report_page.click("li#trv-main-menu-export-command > a", force=True)

        # Download PDF
        with report_page.expect_download() as download_info:
            report_page.wait_for_timeout(500)
            report_page.click("text=Acrobat (PDF) file")
        download = download_info.value
        arrivals_pdf = str(DOWNLOAD_DIR / f"arrivals_{datetime.now().strftime('%Y%m%d')}.pdf")
        download.save_as(arrivals_pdf)
        logger.info(f"✓ Saved Arrival Report (PDF): {arrivals_pdf}")
        
        # Re-click export for CSV
        report_page.wait_for_timeout(1000)
        try:
            export_btns = report_page.locator("[title='Export']")
            for i in range(export_btns.count()):
                if export_btns.nth(i).is_visible():
                    export_btns.nth(i).click()
                    break
        except:
            report_page.click("[title='Export']", force=True)
        
        # Download CSV
        with report_page.expect_download() as download_info:
            report_page.wait_for_timeout(500)
            report_page.click("text=CSV (comma delimited)")
        download = download_info.value
        arrivals_csv = str(DOWNLOAD_DIR / f"arrivals_{datetime.now().strftime('%Y%m%d')}.csv")
        download.save_as(arrivals_csv)
        logger.info(f"✓ Saved Arrival Report (CSV): {arrivals_csv}")
        
        # Close the report tab
        report_page.close()
        page.wait_for_timeout(2000)
        
        # Go back to Report List
        page.goto("https://reimasterapps.com.au/report/reportlist?reicid=758", timeout=30000)
        page.wait_for_timeout(3000)
        
        # ===== DEPARTURE REPORT =====
        logger.info("Generating Departure Report for tomorrow...")
        
        # Click on Departure Report
        page.click("text=Departure Report")
        page.wait_for_timeout(2000)
        
        # Configure hide options
        logger.info("Configuring report options (Hide toggles)...")
        configure_report_options(page)
        
        # Select Tomorrow in the popup
        page.click("text=Tomorrow")
        page.wait_for_timeout(1000)
        
        # Click Preview button - this opens a new tab
        with context.expect_page() as new_page_info:
            page.click("a#btnPreviewBookingDate")
        report_page = new_page_info.value
        report_page.wait_for_load_state("networkidle")
        logger.info("Report preview opened in new tab")
        
        # Click the save/export dropdown
        report_page.wait_for_timeout(2000)
        
        # Click the export dropdown button (Departure)
        try:
            export_btns = report_page.locator("[title='Export']")
            count = export_btns.count()
            export_clicked = False
            
            for i in range(count):
                if export_btns.nth(i).is_visible():
                    logger.info("Found visible export button, clicking...")
                    export_btns.nth(i).click()
                    export_clicked = True
                    break
            
            if not export_clicked:
                logger.warning("No visible export button found, attempting force click on first...")
                export_btns.first.click(force=True)
                
        except Exception as e:
            logger.error(f"Error clicking export button: {e}")
            report_page.click("li#trv-main-menu-export-command > a", force=True)

        # Download PDF
        with report_page.expect_download() as download_info:
            report_page.wait_for_timeout(500)
            report_page.click("text=Acrobat (PDF) file")
        download = download_info.value
        departures_pdf = str(DOWNLOAD_DIR / f"departures_{datetime.now().strftime('%Y%m%d')}.pdf")
        download.save_as(departures_pdf)
        logger.info(f"✓ Saved Departure Report (PDF): {departures_pdf}")
        
        # Re-click export for CSV
        report_page.wait_for_timeout(1000)
        try:
            export_btns = report_page.locator("[title='Export']")
            for i in range(export_btns.count()):
                if export_btns.nth(i).is_visible():
                    export_btns.nth(i).click()
                    break
        except:
            report_page.click("[title='Export']", force=True)
        
        # Download CSV
        with report_page.expect_download() as download_info:
            report_page.wait_for_timeout(500)
            report_page.click("text=CSV (comma delimited)")
        download = download_info.value
        departures_csv = str(DOWNLOAD_DIR / f"departures_{datetime.now().strftime('%Y%m%d')}.csv")
        download.save_as(departures_csv)
        logger.info(f"✓ Saved Departure Report (CSV): {departures_csv}")
        
        # Close the report tab
        report_page.close()
        
        logger.info("=" * 60)
        logger.info("✓ Daily reports complete!")
        logger.info(f"  - {arrivals_pdf}")
        logger.info(f"  - {arrivals_csv}")
        logger.info(f"  - {departures_pdf}")
        logger.info(f"  - {departures_csv}")
        logger.info("=" * 60)
        
        # Send reports via API email
        try:
            from api_email_sender import send_reports
            logger.info("Sending reports via email API...")
            if send_reports(arrivals_pdf, departures_pdf, arrivals_csv, departures_csv):
                logger.info("✓ Email sent successfully!")
            else:
                logger.warning("Email sending failed or not configured.")
        except ImportError:
            logger.info("Email API not configured (api_email_sender.py). Skipping email.")
        except Exception as e:
            logger.error(f"Email error: {e}")
            
        # Save state on success
        save_successful_run()
        
    except Exception as e:
        logger.error(f"Report failed: {e}")
        error_details = str(e)
        try:
            scr_path = f"error_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            page.screenshot(path=scr_path)
            logger.info(f"Screenshot saved to {scr_path}")
            error_details += f"\nScreenshot saved as {scr_path}"
        except Exception as scr_err:
            logger.error(f"Could not take screenshot: {scr_err}")
            
        # Send Failure Alert (SMS/Telegram)
        try:
            from api_email_sender import send_failure_alert
            send_failure_alert(error_details)
        except Exception as alert_err:
            logger.error(f"Failed to send failure alert: {alert_err}")


def run_weekly_report():
    """Execute the weekly report workflow: Arrivals and Departures for next 7 days."""
    global page, context
    
    logger.info("=" * 60)
    logger.info(f"RUNNING WEEKLY REPORT - {datetime.now()}")
    logger.info("=" * 60)
    
    try:
        # Go to Report List
        logger.info("Navigating to Report List...")
        page.goto("https://reimasterapps.com.au/report/reportlist?reicid=758", timeout=30000)
        page.wait_for_timeout(3000)
        
        # ===== ARRIVAL REPORT (WEEKLY) =====
        logger.info("Generating Arrival Report for next 7 days...")
        
        # Click on Arrival Report
        try:
            page.click("text=Arrival Report", timeout=5000)
        except:
            logger.info("Retry clicking Arrival Report...")
            page.goto("https://reimasterapps.com.au/report/reportlist?reicid=758")
            page.wait_for_timeout(3000)
            page.click("text=Arrival Report")
            
        page.wait_for_timeout(2000)
        
        # Configure hide options
        logger.info("Configuring report options (Hide toggles)...")
        configure_report_options(page)
        
        # Select Next 7 Days
        logger.info("Selecting 'Next 7 Days' for reports...")
        try:
            page.evaluate("document.querySelector('#bookingNext7').parentNode.querySelector('.iCheck-helper').click()")
        except:
            page.click("label[for='bookingNext7']", force=True)
        page.wait_for_timeout(1000)
        
        # Click Preview button - this opens a new tab
        with context.expect_page() as new_page_info:
            page.click("a#btnPreviewBookingDate")
        report_page = new_page_info.value
        report_page.wait_for_load_state("networkidle")
        logger.info("Report preview opened in new tab")
        
        # Click the export dropdown button
        report_page.wait_for_timeout(2000)
        try:
            export_btns = report_page.locator("[title='Export']")
            count = export_btns.count()
            export_clicked = False
            
            for i in range(count):
                if export_btns.nth(i).is_visible():
                    logger.info("Found visible export button, clicking...")
                    export_btns.nth(i).click()
                    export_clicked = True
                    break
            
            if not export_clicked:
                logger.warning("No visible export button found, attempting force click on first...")
                export_btns.first.click(force=True)
                
        except Exception as e:
            logger.error(f"Error clicking export button: {e}")
            report_page.click("li#trv-main-menu-export-command > a", force=True)

        # Download PDF
        with report_page.expect_download() as download_info:
            report_page.wait_for_timeout(500)
            report_page.click("text=Acrobat (PDF) file")
        download = download_info.value
        arrivals_pdf = str(DOWNLOAD_DIR / f"weekly_arrivals_{datetime.now().strftime('%Y%m%d')}.pdf")
        download.save_as(arrivals_pdf)
        logger.info(f"✓ Saved Weekly Arrival Report (PDF): {arrivals_pdf}")
        
        # Re-click export for CSV
        report_page.wait_for_timeout(1000)
        try:
            export_btns = report_page.locator("[title='Export']")
            for i in range(export_btns.count()):
                if export_btns.nth(i).is_visible():
                    export_btns.nth(i).click()
                    break
        except:
            report_page.click("[title='Export']", force=True)
        
        # Download CSV
        with report_page.expect_download() as download_info:
            report_page.wait_for_timeout(500)
            report_page.click("text=CSV (comma delimited)")
        download = download_info.value
        arrivals_csv = str(DOWNLOAD_DIR / f"weekly_arrivals_{datetime.now().strftime('%Y%m%d')}.csv")
        download.save_as(arrivals_csv)
        logger.info(f"✓ Saved Weekly Arrival Report (CSV): {arrivals_csv}")
        
        # Close the report tab
        report_page.close()
        page.wait_for_timeout(2000)
        
        # Go back to Report List
        page.goto("https://reimasterapps.com.au/report/reportlist?reicid=758", timeout=30000)
        page.wait_for_timeout(3000)
        
        # ===== DEPARTURE REPORT (WEEKLY) =====
        logger.info("Generating Departure Report for next 7 days...")
        
        # Click on Departure Report
        page.click("text=Departure Report")
        page.wait_for_timeout(2000)
        
        # Configure hide options
        logger.info("Configuring report options (Hide toggles)...")
        configure_report_options(page)
        
        # Select Next 7 Days
        try:
            page.evaluate("document.querySelector('#bookingNext7').parentNode.querySelector('.iCheck-helper').click()")
        except:
            page.click("label[for='bookingNext7']", force=True)
        page.wait_for_timeout(1000)
        
        # Click Preview button - this opens a new tab
        with context.expect_page() as new_page_info:
            page.click("a#btnPreviewBookingDate")
        report_page = new_page_info.value
        report_page.wait_for_load_state("networkidle")
        logger.info("Report preview opened in new tab")
        
        # Click the export dropdown button
        report_page.wait_for_timeout(2000)
        try:
            export_btns = report_page.locator("[title='Export']")
            count = export_btns.count()
            export_clicked = False
            
            for i in range(count):
                if export_btns.nth(i).is_visible():
                    logger.info("Found visible export button, clicking...")
                    export_btns.nth(i).click()
                    export_clicked = True
                    break
            
            if not export_clicked:
                logger.warning("No visible export button found, attempting force click on first...")
                export_btns.first.click(force=True)
                
        except Exception as e:
            logger.error(f"Error clicking export button: {e}")
            report_page.click("li#trv-main-menu-export-command > a", force=True)

        # Download PDF
        with report_page.expect_download() as download_info:
            report_page.wait_for_timeout(500)
            report_page.click("text=Acrobat (PDF) file")
        download = download_info.value
        departures_pdf = str(DOWNLOAD_DIR / f"weekly_departures_{datetime.now().strftime('%Y%m%d')}.pdf")
        download.save_as(departures_pdf)
        logger.info(f"✓ Saved Weekly Departure Report (PDF): {departures_pdf}")
        
        # Re-click export for CSV
        report_page.wait_for_timeout(1000)
        try:
            export_btns = report_page.locator("[title='Export']")
            for i in range(export_btns.count()):
                if export_btns.nth(i).is_visible():
                    export_btns.nth(i).click()
                    break
        except:
            report_page.click("[title='Export']", force=True)
        
        # Download CSV
        with report_page.expect_download() as download_info:
            report_page.wait_for_timeout(500)
            report_page.click("text=CSV (comma delimited)")
        download = download_info.value
        departures_csv = str(DOWNLOAD_DIR / f"weekly_departures_{datetime.now().strftime('%Y%m%d')}.csv")
        download.save_as(departures_csv)
        logger.info(f"✓ Saved Weekly Departure Report (CSV): {departures_csv}")
        
        # Close the report tab
        report_page.close()
        
        logger.info("=" * 60)
        logger.info("✓ Weekly reports complete!")
        logger.info(f"  - {arrivals_pdf}")
        logger.info(f"  - {arrivals_csv}")
        logger.info(f"  - {departures_pdf}")
        logger.info(f"  - {departures_csv}")
        logger.info("=" * 60)
        
        # Send reports via API email (reusing daily email function)
        try:
            from api_email_sender import send_reports
            logger.info("Sending weekly reports via email API...")
            if send_reports(arrivals_pdf, departures_pdf, arrivals_csv, departures_csv, report_type="Weekly"):
                logger.info("✓ Weekly email sent successfully!")
                
                # Save state on success (for weekly watchdog)
                save_successful_weekly_run()
            else:
                logger.warning("Weekly email sending failed or not configured.")
        except ImportError:
            logger.info("Email API not configured (api_email_sender.py). Skipping email.")
        except Exception as e:
            logger.error(f"Weekly email error: {e}")
            
    except Exception as e:
        logger.error(f"Weekly report failed: {e}")
        error_details = f"WEEKLY REPORT FAILED: {str(e)}"
        try:
            scr_path = f"weekly_error_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            page.screenshot(path=scr_path)
            logger.info(f"Screenshot saved to {scr_path}")
            error_details += f"\nScreenshot saved as {scr_path}"
        except Exception as scr_err:
            logger.error(f"Could not take screenshot: {scr_err}")
            
        # Send Failure Alert (SMS/Telegram)
        try:
            from api_email_sender import send_failure_alert
            send_failure_alert(error_details)
        except Exception as alert_err:
            logger.error(f"Failed to send failure alert: {alert_err}")

def run_daily_status_check():
    """
    Daily heartbeat notification via Telegram at 9 PM.
    """
    logger.info("Running daily status check...")
    try:
        from api_email_sender import send_telegram_notification
        from datetime import datetime
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        msg = f"✅ Automation Status Check\nTime: {now_str}\nStatus: Running correctly"
        
        if send_telegram_notification(msg):
            logger.info("✓ Daily status notification sent via Telegram.")
        else:
            logger.warning("Failed to send daily status notification.")
            
    except ImportError:
        logger.error("Could not import send_telegram_notification from api_email_sender")
    except Exception as e:
        logger.error(f"Error sending daily status: {e}")



def heartbeat_check():
    """
    Heartbeat to keep session alive and verify browser is authenticated.
    Navigates between pages to generate server activity, then verifies login status.
    Runs every 30 minutes. If session expired, attempts auto re-login.
    Alerts via SMS/Telegram only if re-login also fails.
    """
    global page, context, playwright_instance
    
    logger.info("💓 Running heartbeat check (keep-alive)...")
    
    try:
        # Check 1: Is playwright/browser still running?
        if not playwright_instance or not context or not page:
            raise Exception("Browser instance not running")
        
        # Step 1: Navigate to Reports page first (generates server activity)
        try:
            logger.info("  → Navigating to Reports page...")
            page.goto("https://reimasterapps.com.au/report/reportlist?reicid=758", timeout=30000)
            page.wait_for_timeout(2000)
        except Exception as nav_error:
            raise Exception(f"Navigation to Reports failed: {nav_error}")
        
        # Check for login redirect after Reports page
        current_url = page.url.lower()
        if "login" in current_url or "account" in current_url or "b2clogin" in current_url:
            raise Exception("Session expired - redirected to login page")
        
        # Step 2: Navigate back to Dashboard (second navigation = more activity)
        try:
            logger.info("  → Navigating back to Dashboard...")
            page.goto("https://reimasterapps.com.au/Customers/Dashboard?reicid=758", timeout=30000)
            page.wait_for_timeout(2000)
        except Exception as nav_error:
            raise Exception(f"Navigation to Dashboard failed: {nav_error}")
        
        # Check 3: Are we on the login page? (indicates session expired)
        current_url = page.url.lower()
        if "login" in current_url or "account" in current_url or "b2clogin" in current_url:
            raise Exception("Session expired - redirected to login page")
        
        # Check 4: Look for a known dashboard element to confirm we're logged in
        try:
            # Look for the Dashboard title or any element that only shows when logged in
            dashboard_visible = page.locator("text=Dashboard").first.is_visible(timeout=5000)
            if not dashboard_visible:
                raise Exception("Dashboard element not found - may not be authenticated")
        except:
            # Try alternative check
            page_content = page.content()
            if "login" in page_content.lower() and "password" in page_content.lower():
                raise Exception("Login form detected - session expired")
        
        logger.info("✓ Heartbeat OK - Session active and kept alive")
        return True
        
    except Exception as e:
        error_msg = f"HEARTBEAT ISSUE: {str(e)}"
        logger.warning(error_msg)
        
        # Attempt auto re-login before alerting
        if REI_USERNAME and REI_PASSWORD:
            logger.info("🔄 Attempting automatic re-login...")
            if auto_login():
                logger.info("✓ Re-login successful! Session restored.")
                return True
            else:
                logger.error("❌ Re-login failed!")
        
        # Re-login failed or no credentials - send alert
        alert_msg = f"HEARTBEAT FAILED: {str(e)} - Auto re-login also failed or not configured."
        
        try:
            if page:
                scr_path = f"error_heartbeat_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                page.screenshot(path=scr_path)
                logger.info(f"Screenshot saved to {scr_path}")
                alert_msg += f"\nScreenshot saved as {scr_path}"
        except Exception as scr_err:
            logger.error(f"Could not take screenshot: {scr_err}")

        logger.error(alert_msg)
        
        try:
            from api_email_sender import send_failure_alert
            send_failure_alert(alert_msg)
        except Exception as alert_err:
            logger.error(f"Failed to send heartbeat alert: {alert_err}")
        
        return False


def auto_login():
    """
    Automatically log in to REI Cloud using credentials from .env.
    Handles the Azure B2C login flow, including the quirk where
    credentials need to be entered twice.
    
    REI Cloud uses Azure B2C with these form elements:
    - Email: input#email (type="email", name="Email Address")
    - Password: input#password (type="password")
    - Submit: button#next (type="submit", text="Sign in")
    """
    global page
    
    if not REI_USERNAME or not REI_PASSWORD:
        logger.info("No REI credentials configured - manual login required")
        return False
    
    logger.info("Attempting auto-login to REI Cloud...")
    
    # Azure B2C sometimes requires entering credentials twice
    max_attempts = 2
    
    for attempt in range(1, max_attempts + 1):
        try:
            logger.info(f"  Login attempt {attempt}/{max_attempts}...")
            
            # Wait for page to settle
            page.wait_for_timeout(3000)
            
            # Check if we're already logged in
            current_url = page.url.lower()
            if "reimasterapps.com.au" in current_url and "b2clogin" not in current_url:
                logger.info("✓ Already logged in!")
                return True
            
            # Check if we're on a login page (Azure B2C)
            if "b2clogin" not in current_url and "login" not in current_url:
                logger.info("Not on login page - may already be logged in")
                return True
            
            # Wait for the email field to be visible (confirms page is ready)
            logger.info("  → Waiting for login form...")
            try:
                page.wait_for_selector("input#email", state="visible", timeout=10000)
            except Exception as e:
                logger.error(f"Login form did not appear: {e}")
                if attempt < max_attempts:
                    continue
                return False
            
            # Fill email field
            logger.info("  → Filling in email...")
            try:
                email_field = page.locator("input#email")
                email_field.fill(REI_USERNAME)
                page.wait_for_timeout(500)
            except Exception as e:
                logger.error(f"Could not fill email field: {e}")
                return False
            
            # Fill password field
            logger.info("  → Filling in password...")
            try:
                password_field = page.locator("input#password")
                password_field.fill(REI_PASSWORD)
                page.wait_for_timeout(500)
            except Exception as e:
                logger.error(f"Could not fill password field: {e}")
                return False
            
            # Click the Sign In button
            logger.info("  → Clicking 'Sign in' button...")
            try:
                submit_btn = page.locator("button#next")
                submit_btn.click()
            except Exception as e:
                logger.error(f"Could not click submit button: {e}")
                return False
            
            # Wait for navigation
            logger.info("  → Waiting for response...")
            page.wait_for_timeout(5000)
            
            # Check where we are now
            current_url = page.url.lower()
            
            # Success - landed on REI Cloud
            if "reimasterapps.com.au" in current_url and "b2clogin" not in current_url:
                logger.info("✓ Auto-login successful!")
                return True
            
            # Still on login page - check for actual visible errors
            if "b2clogin" in current_url or "login" in current_url:
                # Azure B2C shows errors in a specific error element, not just anywhere on the page
                # Check for visible error messages using known B2C error selectors
                try:
                    # Common Azure B2C error selectors
                    error_selectors = [
                        ".error.itemLevel",  # B2C item-level error
                        ".error.pageLevel",  # B2C page-level error
                        "#error",            # Generic error div
                        ".error-message",    # Alternative error class
                        "[aria-live='polite'].error"  # Accessible error
                    ]
                    
                    has_visible_error = False
                    for selector in error_selectors:
                        try:
                            error_elem = page.locator(selector)
                            if error_elem.count() > 0 and error_elem.first.is_visible():
                                error_text = error_elem.first.text_content() or ""
                                if error_text.strip():  # Only count if there's actual text
                                    logger.error(f"Login failed - error shown: {error_text.strip()}")
                                    has_visible_error = True
                                    break
                        except:
                            continue
                    
                    if has_visible_error:
                        return False
                        
                except Exception as err_check:
                    logger.debug(f"Error checking for login errors: {err_check}")
                
                # No visible error, might just need another attempt (Azure B2C quirk)
                logger.info(f"  Still on login page, will retry...")
                continue
                
        except Exception as e:
            logger.error(f"Auto-login attempt {attempt} error: {e}")
            if attempt >= max_attempts:
                return False
    
    logger.warning("Auto-login: max attempts reached, still on login page")
    return False


def input_listener(stop_event, trigger_daily_event, trigger_weekly_event):
    """Listens for 'run_d' or 'run_w' command in a separate thread."""
    while not stop_event.is_set():
        try:
            line = sys.stdin.readline()
            if not line:
                break
            cmd = line.strip().lower()
            if cmd == "run_d" and not stop_event.is_set():
                trigger_daily_event.set()
            elif cmd == "run_w" and not stop_event.is_set():
                trigger_weekly_event.set()
            elif cmd and not stop_event.is_set():
                logger.info("Type 'run_d' for daily report or 'run_w' for weekly report.")
        except:
            break

def setup_browser():
    """Start Playwright and Browser."""
    global playwright_instance, browser, context, page
    
    playwright_instance = sync_playwright().start()
    
    # Use persistent context to save login state
    user_data_dir = os.path.expanduser("~/.rei-browser-profile")
    if not os.path.exists(user_data_dir):
        os.makedirs(user_data_dir)
        
    logger.info(f"Using browser profile: {user_data_dir}")
    
    # Launch with persistent context
    context = playwright_instance.chromium.launch_persistent_context(
        user_data_dir=user_data_dir,
        headless=False,
        viewport={"width": 1280, "height": 800},
        accept_downloads=True,
        args=["--disable-blink-features=AutomationControlled"]
    )
    
    page = context.pages[0] if context.pages else context.new_page()

    # Handle new tabs (popups) by adding them to context tracking if strictly needed,
    # but our logic now handles new_page_info which is better.
    # We remove the aggressive popup handler that forced closing.


def main():
    global page
    
    # Handle Ctrl+C gracefully
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)
    
    record_mode = "--record" in sys.argv
    test_mode = "--test" in sys.argv
    run_now = "--run-now" in sys.argv
    run_weekly = "--run-weekly" in sys.argv
    run_bookings_hist = "--run-historical-bookings" in sys.argv
    run_bookings_maint = "--run-maintenance-bookings" in sys.argv
    
    logger.info("=" * 60)
    logger.info("REI CLOUD AUTOMATION")
    if record_mode:
        logger.info("MODE: Recording workflow")
    elif test_mode:
        logger.info("MODE: Test (every 5 minutes)")
    else:
        logger.info("MODE: Production (daily at 08:00)")
    logger.info("Press Ctrl+C to stop")
    logger.info("=" * 60)
    
    # Start browser
    setup_browser()
    
    # Navigate
    logger.info(f"Opening {REI_CLOUD_URL}")
    page.goto(REI_CLOUD_URL, timeout=60000)
    
    # Check if already logged in (quick check by URL)
    is_logged_in = False
    try:
        if "Dashboard" in page.url or "reimasterapps.com.au" in page.url and "b2clogin" not in page.url:
            is_logged_in = True
    except:
        pass
    
    # Try auto-login if not logged in and credentials are available
    if not is_logged_in and REI_USERNAME and REI_PASSWORD:
        logger.info("Credentials found in .env - attempting auto-login...")
        if auto_login():
            is_logged_in = True
            # Give it a moment to fully load dashboard
            page.wait_for_timeout(3000)
            # Verify we're on dashboard
            try:
                if "Dashboard" in page.url or ("reimasterapps.com.au" in page.url and "b2clogin" not in page.url):
                    is_logged_in = True
                else:
                    is_logged_in = False
            except:
                is_logged_in = False
    
    logger.info("")
    logger.info("=" * 60)
    if is_logged_in:
        logger.info("✓ Logged in successfully!")
        logger.info("Starting automation in 3 seconds...")
        logger.info("=" * 60)
        time.sleep(3)  # Brief pause before starting
    else:
        if REI_USERNAME and REI_PASSWORD:
            logger.warning("Auto-login failed. Please log in manually.")
        logger.info("LOG IN to REI Master Apps in the browser window.")
        logger.info("When you're logged in and on the dashboard,")
        logger.info("come back here and press ENTER to continue...")
        logger.info("=" * 60)
        sys.stdin.readline()  # Wait for Enter
    
    logger.info("✓ Starting automation engine...")
    
    # If Recording Mode
    if record_mode:
        recorded_urls = [page.url]
        last_url = page.url
        logger.info(f"recording: {page.url}")
        
        try:
            while True:
                time.sleep(1)
                try:
                    current_url = page.url
                    if current_url != last_url:
                        logger.info(f"visited: {current_url}")
                        recorded_urls.append(current_url)
                        last_url = current_url
                except:
                    pass
        except KeyboardInterrupt:
            logger.info("Recording complete.")
            cleanup()
            return

    # Normal Schedule Mode (all times in Australia/Brisbane timezone)
    if test_mode:
        logger.info("Scheduling report every 5 minutes")
        schedule.every(5).minutes.do(run_daily_report)
    else:
        logger.info("Scheduling report daily at 13:00 Brisbane time")
        schedule.every().day.at("13:00", "Australia/Brisbane").do(run_daily_report)

    # Weekly report every Saturday at 08:00 AM Brisbane time
    logger.info("Scheduling weekly report every Saturday at 08:00 Brisbane time")
    schedule.every().saturday.at("08:00", "Australia/Brisbane").do(run_weekly_report)

    # Daily Status Check (Telegram) at 9:00 PM Brisbane time
    logger.info("Scheduling daily status check at 21:00 Brisbane time")
    schedule.every().day.at("21:00", "Australia/Brisbane").do(run_daily_status_check)
    
    # Heartbeat check every 30 minutes to keep session alive and verify authentication
    logger.info("Scheduling heartbeat check every 30 minutes")
    schedule.every(30).minutes.do(heartbeat_check)
    
    # Booking Data Extraction Maintenance
    logger.info("Scheduling booking data extraction maintenance daily at 14:00 Brisbane time")
    schedule.every().day.at("14:00", "Australia/Brisbane").do(run_booking_maintenance)
    
    # Run immediately if --run-now (first time)
    if run_now:
        logger.info("Running initial daily report (--run-now)...")
        run_daily_report()
    
    # Run weekly immediately if --run-weekly
    if run_weekly:
        logger.info("Running weekly report (--run-weekly)...")
        run_weekly_report()
    
    if run_bookings_hist:
        logger.info("Running historical booking extraction (--run-historical-bookings)...")
        run_booking_historical()
        
    if run_bookings_maint:
        logger.info("Running booking extraction maintenance (--run-maintenance-bookings)...")
        run_booking_maintenance()
    
    logger.info("=" * 60)
    logger.info("AUTOMATION IS LIVE")
    logger.info(f"1. Daily report scheduled at {SCHEDULED_RUN_HOUR:02d}:{SCHEDULED_RUN_MINUTE:02d}")
    logger.info("2. Weekly report scheduled every Saturday at 08:00")
    logger.info("3. Heartbeat check every 30 minutes (keeps session alive)")
    logger.info("4. Type 'run_d' for daily report, 'run_w' for weekly report")
    logger.info("5. Press Ctrl+C to exit")
    logger.info("Automation engine started.")

    # Send startup notification
    try: 
        from api_email_sender import send_telegram_notification
        send_telegram_notification("🚀 Automation is Live\nSystem initialized and ready.")
    except Exception as e:
        logger.warning(f"Failed to send startup notification: {e}")

    # Setup background thread to listen for manual trigger commands
    stop_event = threading.Event()
    trigger_daily_event = threading.Event()
    trigger_weekly_event = threading.Event()
    input_thread = threading.Thread(target=input_listener, args=(stop_event, trigger_daily_event, trigger_weekly_event), daemon=True)
    input_thread.start()

    # Initialize state if needed (sets next_expected_run)
    init_state_if_needed()
    init_weekly_state_if_needed()
    
    alert_sent_for_current_deadline = False
    current_deadline_str = None  # Track which deadline we've alerted for

    weekly_alert_sent_for_current_deadline = False
    current_weekly_deadline_str = None  # Track which weekly deadline we've alerted for

    # Main Loop
    try:
        while True:
            schedule.run_pending()
            
            # Watchdog: Check for missed run using deadline-based logic
            # Only alert if: past deadline (scheduled time + grace period) AND no success since deadline
            is_past, next_expected_dt, last_success_dt = is_past_deadline()
            
            if is_past and next_expected_dt:
                deadline_str = next_expected_dt.isoformat()
                
                # Reset alert flag when deadline changes (new day)
                if deadline_str != current_deadline_str:
                    current_deadline_str = deadline_str
                    alert_sent_for_current_deadline = False
                
                # Check if we should alert
                if not alert_sent_for_current_deadline:
                    # No successful run before this deadline?
                    missed_run = (last_success_dt is None) or (last_success_dt < next_expected_dt)
                    
                    if missed_run:
                        alert_sent_for_current_deadline = True
                        now = datetime.now()
                        msg = f"MISSED SCHEDULED RUN. Expected by: {next_expected_dt.strftime('%Y-%m-%d %H:%M')}. Current time: {now.strftime('%H:%M')}. Please check server."
                        logger.warning(msg)
                        
                        try:
                            from api_email_sender import send_failure_alert
                            send_failure_alert(msg)
                        except Exception as ex:
                            logger.error(f"Failed to send missed run alert: {ex}")
                    else:
                        # We already have a successful run for this deadline, just set flag
                        alert_sent_for_current_deadline = True

            # Weekly Watchdog: Check for missed weekly run using deadline-based logic
            is_past_weekly, next_expected_weekly_dt, last_weekly_success_dt = is_past_weekly_deadline()

            if is_past_weekly and next_expected_weekly_dt:
                weekly_deadline_str = next_expected_weekly_dt.isoformat()
                
                # Reset alert flag when deadline changes (new week)
                if weekly_deadline_str != current_weekly_deadline_str:
                    current_weekly_deadline_str = weekly_deadline_str
                    weekly_alert_sent_for_current_deadline = False
                
                # Check if we should alert
                if not weekly_alert_sent_for_current_deadline:
                    # No successful run before this deadline?
                    missed_weekly_run = (last_weekly_success_dt is None) or (last_weekly_success_dt < next_expected_weekly_dt)
                    
                    if missed_weekly_run:
                        weekly_alert_sent_for_current_deadline = True
                        now = datetime.now()
                        msg = f"MISSED WEEKLY SCHEDULED RUN. Expected by: {next_expected_weekly_dt.strftime('%Y-%m-%d %H:%M')} (Saturday). Current time: {now.strftime('%Y-%m-%d %H:%M')}. Please check server."
                        logger.warning(msg)
                        
                        try:
                            from api_email_sender import send_failure_alert
                            send_failure_alert(msg)
                        except Exception as ex:
                            logger.error(f"Failed to send missed weekly run alert: {ex}")
                    else:
                        # We already have a successful run for this deadline, just set flag
                        weekly_alert_sent_for_current_deadline = True

            # Handle manual daily trigger
            if trigger_daily_event.is_set():
                trigger_daily_event.clear()
                logger.info("Manual daily trigger detected! Starting daily report...")
                run_daily_report()
                logger.info("Daily report complete. Type 'run_d' or 'run_w' to trigger manually.")
            
            # Handle manual weekly trigger
            if trigger_weekly_event.is_set():
                trigger_weekly_event.clear()
                logger.info("Manual weekly trigger detected! Starting weekly report...")
                run_weekly_report()
                logger.info("Weekly report complete. Type 'run_d' or 'run_w' to trigger manually.")                
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("\nStopping...")
        stop_event.set()
        cleanup()

if __name__ == "__main__":
    main()
