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
from datetime import datetime
from pathlib import Path

import schedule
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

load_dotenv()

# Configuration
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "./downloads"))
REI_CLOUD_URL = "https://reimasterapps.com.au/Customers/Dashboard?reicid=758"

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

        # Click PDF option
        with report_page.expect_download() as download_info:
            report_page.wait_for_timeout(500)
            report_page.click("text=Acrobat (PDF) file")
        
        download = download_info.value
        arrivals_path = str(DOWNLOAD_DIR / f"arrivals_{datetime.now().strftime('%Y%m%d')}.pdf")
        download.save_as(arrivals_path)
        logger.info(f"✓ Saved Arrival Report: {arrivals_path}")
        
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
            # Try specific ID as fallback
            report_page.click("li#trv-main-menu-export-command > a", force=True)

        with report_page.expect_download() as download_info:
            report_page.wait_for_timeout(500)
            report_page.click("text=Acrobat (PDF) file")
        
        download = download_info.value
        departures_path = str(DOWNLOAD_DIR / f"departures_{datetime.now().strftime('%Y%m%d')}.pdf")
        download.save_as(departures_path)
        logger.info(f"✓ Saved Departure Report: {departures_path}")
        
        # Close the report tab
        report_page.close()
        
        logger.info("=" * 60)
        logger.info("✓ Daily reports complete!")
        logger.info(f"  - {arrivals_path}")
        logger.info(f"  - {departures_path}")
        logger.info("=" * 60)
        
        # Optional: Email the reports
        # from email_sender import send_email_with_attachment
        # send_email_with_attachment(arrivals_path, "arrivals.pdf")
        # send_email_with_attachment(departures_path, "departures.pdf")
        
    except Exception as e:
        logger.error(f"Report failed: {e}")
        try:
            page.screenshot(path=f"error_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        except:
            pass


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
        
    logger.info("")
    logger.info("=" * 60)
    if is_logged_in:
        logger.info("Looks like you might be logged in (or close to it).")
        logger.info("If you are on the Dashboard, press ENTER to start automation.")
    else:
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
        logger.info("Scheduling report daily at 08:00")
        schedule.every().day.at("08:00").do(run_daily_report)
    
    # Run immediately if --run-now (first time)
    if run_now:
        logger.info("Running initial report (--run-now)...")
        run_daily_report()
    
    logger.info("=" * 60)
    logger.info("AUTOMATION IS LIVE")
    logger.info("1. Scheduled to run daily at 08:00")
    logger.info("2. Press ENTER at any time to run MANUALLY")
    logger.info("3. Press Ctrl+C to exit")
    logger.info("=" * 60)
    
    # Setup background thread to listen for ENTER key
    stop_event = threading.Event()
    trigger_event = threading.Event()
    input_thread = threading.Thread(target=input_listener, args=(stop_event, trigger_event), daemon=True)
    input_thread.start()
    
    # Main Loop
    try:
        while True:
            schedule.run_pending()
            
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
