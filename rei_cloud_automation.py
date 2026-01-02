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
from datetime import datetime
from pathlib import Path

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

def load_state():
    """Load the last successful run date."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return {}

def save_state(date_str):
    """Save the last successful run date."""
    try:
        current = load_state()
        current["last_run_date"] = date_str
        with open(STATE_FILE, "w") as f:
            json.dump(current, f)
    except Exception as e:
        logger.error(f"Failed to save state: {e}")

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
            from api_email_sender import send_daily_reports
            logger.info("Sending reports via email API...")
            if send_daily_reports(arrivals_pdf, departures_pdf, arrivals_csv, departures_csv):
                logger.info("✓ Email sent successfully!")
            else:
                logger.warning("Email sending failed or not configured.")
        except ImportError:
            logger.info("Email API not configured (api_email_sender.py). Skipping email.")
        except Exception as e:
            logger.error(f"Email error: {e}")
            
        # Save state on success
        save_state(datetime.now().strftime("%Y-%m-%d"))
        
    except Exception as e:
        logger.error(f"Report failed: {e}")
        try:
            page.screenshot(path=f"error_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        except:
            pass
            
        # Send Failure Alert (SMS/Telegram)
        try:
            from api_email_sender import send_failure_alert
            send_failure_alert(str(e))
        except Exception as alert_err:
            logger.error(f"Failed to send failure alert: {alert_err}")


def heartbeat_check():
    """
    Heartbeat to keep session alive and verify browser is authenticated.
    Navigates between pages to generate server activity, then verifies login status.
    Runs every 30 minutes. Alerts via SMS/Telegram if session is dead or unauthenticated.
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
        error_msg = f"HEARTBEAT FAILED: {str(e)}"
        logger.error(error_msg)
        
        # Send alert
        try:
            from api_email_sender import send_failure_alert
            send_failure_alert(error_msg)
        except Exception as alert_err:
            logger.error(f"Failed to send heartbeat alert: {alert_err}")
        
        return False


def auto_login():
    """
    Automatically log in to REI Cloud using credentials from .env.
    Handles the Azure B2C login flow.
    Returns True if login successful, False otherwise.
    
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
    
    try:
        # Wait for login page to fully load
        logger.info("  → Waiting for login page to load...")
        page.wait_for_timeout(3000)
        
        # Check if we're on a login page (Azure B2C)
        current_url = page.url.lower()
        if "b2clogin" not in current_url and "login" not in current_url:
            # Already logged in or on dashboard
            logger.info("Not on login page - may already be logged in")
            return True
        
        # Wait for the email field to be visible (confirms page is ready)
        logger.info("  → Waiting for login form...")
        try:
            page.wait_for_selector("input#email", state="visible", timeout=10000)
        except Exception as e:
            logger.error(f"Login form did not appear: {e}")
            return False
        
        # Fill email field (REI Cloud uses input#email)
        logger.info("  → Filling in email...")
        try:
            email_field = page.locator("input#email")
            email_field.fill(REI_USERNAME)
            page.wait_for_timeout(500)
        except Exception as e:
            logger.error(f"Could not fill email field: {e}")
            return False
        
        # Fill password field (REI Cloud uses input#password)
        logger.info("  → Filling in password...")
        try:
            password_field = page.locator("input#password")
            password_field.fill(REI_PASSWORD)
            page.wait_for_timeout(500)
        except Exception as e:
            logger.error(f"Could not fill password field: {e}")
            return False
        
        # Click the Sign In button (REI Cloud uses button#next)
        logger.info("  → Clicking 'Sign in' button...")
        try:
            submit_btn = page.locator("button#next")
            submit_btn.click()
        except Exception as e:
            logger.error(f"Could not click submit button: {e}")
            return False
        
        # Wait for navigation to complete
        logger.info("  → Waiting for login to complete...")
        page.wait_for_timeout(8000)  # Give more time for Azure B2C redirect
        
        # Check if we're now on dashboard (successful login)
        current_url = page.url.lower()
        if "b2clogin" in current_url or "login" in current_url:
            # Still on login page - check for error message
            page_content = page.content().lower()
            if "error" in page_content or "incorrect" in page_content or "invalid" in page_content:
                logger.error("Login failed - incorrect credentials")
                return False
            logger.warning("Still on login page after submit - may need MFA or additional steps")
            return False
        
        # Verify we landed on a REI Cloud page
        if "reimasterapps.com.au" in current_url:
            logger.info("✓ Auto-login successful!")
            return True
        else:
            logger.warning(f"Unexpected URL after login: {page.url}")
            return False
        
    except Exception as e:
        logger.error(f"Auto-login error: {e}")
        return False


def input_listener(stop_event, trigger_event):
    """Listens for user input in a separate thread."""
    while not stop_event.is_set():
        try:
            # This blocks, but it's in a daemon thread so it's fine
            line = sys.stdin.readline()
            if not line:
                break
            if not stop_event.is_set():
                trigger_event.set()
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

    # Normal Schedule Mode
    if test_mode:
        logger.info("Scheduling report every 5 minutes")
        schedule.every(5).minutes.do(run_daily_report)
    else:
        logger.info("Scheduling report daily at 06:01")
        schedule.every().day.at("06:01").do(run_daily_report)
    
    # Heartbeat check every 30 minutes to keep session alive and verify authentication
    logger.info("Scheduling heartbeat check every 30 minutes")
    schedule.every(30).minutes.do(heartbeat_check)
    
    # Run immediately if --run-now (first time)
    if run_now:
        logger.info("Running initial report (--run-now)...")
        run_daily_report()
    
    logger.info("=" * 60)
    logger.info("AUTOMATION IS LIVE")
    logger.info("1. Scheduled to run daily at 06:01")
    logger.info("2. Heartbeat check every 30 minutes (keeps session alive)")
    logger.info("3. Press ENTER at any time to run MANUALLY")
    logger.info("3. Press Ctrl+C to exit")
    logger.info("Automation engine started.")

    # Setup background thread to listen for ENTER key
    stop_event = threading.Event()
    trigger_event = threading.Event()
    input_thread = threading.Thread(target=input_listener, args=(stop_event, trigger_event), daemon=True)
    input_thread.start()

    alert_sent_today = False 

    # Main Loop
    try:
        while True:
            schedule.run_pending()
            
            # Watchdog: Check for missed run
            # If it is past 00:30 and we haven't run today, trigger alert
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")
            
            # Reset alert flag at midnight (or close to it)
            if now.hour == 0 and now.minute < 5:
                alert_sent_today = False

            if now.hour > 0 and not alert_sent_today:
                # Check state
                state = load_state()
                last_run = state.get("last_run_date")
                
                if last_run != today_str:
                    # MISSED RUN DETECTED!
                    msg = f"MISSED SCHEDULED RUN for {today_str}. Current time: {now.strftime('%H:%M')}. Please check server."
                    logger.warning(msg)
                    
                    try:
                        from api_email_sender import send_failure_alert
                        send_failure_alert(msg)
                        alert_sent_today = True # Only alert once per day
                    except Exception as ex:
                        logger.error(f"Failed to send missed run alert: {ex}")

            if trigger_event.is_set():
                trigger_event.clear()
                logger.info("Manual trigger detected! Starting report...")
                run_daily_report()
                logger.info("Report complete. Waiting for next schedule or manual trigger (Enter).")
                
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("\nStopping...")
        stop_event.set()
        cleanup()

if __name__ == "__main__":
    main()
