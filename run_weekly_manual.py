#!/usr/bin/env python3
"""
One-off weekly report runner
"""
import os
import sys
import logging
from datetime import datetime
from pathlib import Path

# Setup paths
os.chdir('/opt/paradise-automator')
sys.path.insert(0, '/opt/paradise-automator')

# Load env
from dotenv import load_dotenv
load_dotenv('/etc/paradise-automator/.env')

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("/opt/paradise-automator/weekly_manual.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

from playwright.sync_api import sync_playwright

DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "/opt/paradise-automator/downloads"))
DOWNLOAD_DIR.mkdir(exist_ok=True)

REI_CLOUD_URL = "https://reimasterapps.com.au/Customers/Dashboard?reicid=758"
REI_USERNAME = os.getenv("REI_USERNAME", "")
REI_PASSWORD = os.getenv("REI_PASSWORD", "")

def configure_report_options(target_page):
    """Enable 'Hide' options in the report modal."""
    hide_options = [
        ("hide_account_balances", "Hide Account Balances"),
        ("hide_guest_comment", "Hide Guest Comments"),
        ("hide_manager_comments", "Hide Manager Comments"),
    ]
    
    for option_id, option_name in hide_options:
        try:
            checkbox = target_page.locator(f"#{option_id}")
            if checkbox.count() > 0:
                is_checked = checkbox.is_checked()
                if not is_checked:
                    switch_wrapper = target_page.locator(f".bootstrap-switch-id-{option_id}")
                    if switch_wrapper.count() > 0:
                        switch_wrapper.click()
                        logger.info(f"  ✓ Enabled: {option_name}")
                    else:
                        checkbox.click()
                        logger.info(f"  ✓ Enabled (fallback): {option_name}")
                else:
                    logger.info(f"  - Already enabled: {option_name}")
        except Exception as e:
            logger.warning(f"  Could not set {option_name}: {e}")
    
    target_page.wait_for_timeout(500)


def run_weekly():
    logger.info("=" * 60)
    logger.info(f"MANUAL WEEKLY REPORT - {datetime.now()}")
    logger.info("=" * 60)
    
    with sync_playwright() as p:
        # Use persistent context to save login state
        user_data_dir = os.path.expanduser("~/.rei-browser-profile")
        if not os.path.exists(user_data_dir):
            os.makedirs(user_data_dir)
        
        context = p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False,
            viewport={"width": 1280, "height": 800},
            accept_downloads=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        
        page = context.pages[0] if context.pages else context.new_page()
        
        try:
            # Navigate to dashboard
            logger.info(f"Opening {REI_CLOUD_URL}")
            page.goto(REI_CLOUD_URL, timeout=60000)
            page.wait_for_timeout(3000)
            
            # Check if logged in
            if "login" in page.url.lower() or "b2clogin" in page.url.lower():
                logger.info("Need to log in...")
                # Try auto-login
                if REI_USERNAME and REI_PASSWORD:
                    page.wait_for_selector("input#email", state="visible", timeout=10000)
                    page.locator("input#email").fill(REI_USERNAME)
                    page.locator("input#password").fill(REI_PASSWORD)
                    page.locator("button#next").click()
                    page.wait_for_timeout(5000)
                else:
                    logger.error("Not logged in and no credentials configured")
                    return False
            
            logger.info("✓ Logged in, navigating to Report List...")
            page.goto("https://reimasterapps.com.au/report/reportlist?reicid=758", timeout=30000)
            page.wait_for_timeout(3000)
            
            # ===== ARRIVAL REPORT (WEEKLY) =====
            logger.info("Generating Arrival Report for next 7 days...")
            
            page.click("text=Arrival Report", timeout=5000)
            page.wait_for_timeout(2000)
            
            configure_report_options(page)
            
            # Select Next 7 Days
            logger.info("Selecting 'Next 7 Days' for reports...")
            try:
                page.evaluate("document.querySelector('#bookingNext7').parentNode.querySelector('.iCheck-helper').click()")
            except:
                page.click("label[for='bookingNext7']", force=True)
            page.wait_for_timeout(1000)
            
            # Click Preview
            with context.expect_page() as new_page_info:
                page.click("a#btnPreviewBookingDate")
            report_page = new_page_info.value
            report_page.wait_for_load_state("networkidle")
            logger.info("Report preview opened in new tab")
            
            # Download PDF
            report_page.wait_for_timeout(2000)
            export_btns = report_page.locator("[title='Export']")
            for i in range(export_btns.count()):
                if export_btns.nth(i).is_visible():
                    export_btns.nth(i).click()
                    break
            
            with report_page.expect_download() as download_info:
                report_page.wait_for_timeout(500)
                report_page.click("text=Acrobat (PDF) file")
            download = download_info.value
            arrivals_pdf = str(DOWNLOAD_DIR / f"weekly_arrivals_{datetime.now().strftime('%Y%m%d')}.pdf")
            download.save_as(arrivals_pdf)
            logger.info(f"✓ Saved Weekly Arrival Report (PDF): {arrivals_pdf}")
            
            # Download CSV
            report_page.wait_for_timeout(1000)
            export_btns = report_page.locator("[title='Export']")
            for i in range(export_btns.count()):
                if export_btns.nth(i).is_visible():
                    export_btns.nth(i).click()
                    break
            
            with report_page.expect_download() as download_info:
                report_page.wait_for_timeout(500)
                report_page.click("text=CSV (comma delimited)")
            download = download_info.value
            arrivals_csv = str(DOWNLOAD_DIR / f"weekly_arrivals_{datetime.now().strftime('%Y%m%d')}.csv")
            download.save_as(arrivals_csv)
            logger.info(f"✓ Saved Weekly Arrival Report (CSV): {arrivals_csv}")
            
            report_page.close()
            page.wait_for_timeout(2000)
            
            # Go back to Report List
            page.goto("https://reimasterapps.com.au/report/reportlist?reicid=758", timeout=30000)
            page.wait_for_timeout(3000)
            
            # ===== DEPARTURE REPORT (WEEKLY) =====
            logger.info("Generating Departure Report for next 7 days...")
            
            page.click("text=Departure Report")
            page.wait_for_timeout(2000)
            
            configure_report_options(page)
            
            try:
                page.evaluate("document.querySelector('#bookingNext7').parentNode.querySelector('.iCheck-helper').click()")
            except:
                page.click("label[for='bookingNext7']", force=True)
            page.wait_for_timeout(1000)
            
            with context.expect_page() as new_page_info:
                page.click("a#btnPreviewBookingDate")
            report_page = new_page_info.value
            report_page.wait_for_load_state("networkidle")
            logger.info("Report preview opened in new tab")
            
            report_page.wait_for_timeout(2000)
            export_btns = report_page.locator("[title='Export']")
            for i in range(export_btns.count()):
                if export_btns.nth(i).is_visible():
                    export_btns.nth(i).click()
                    break
            
            with report_page.expect_download() as download_info:
                report_page.wait_for_timeout(500)
                report_page.click("text=Acrobat (PDF) file")
            download = download_info.value
            departures_pdf = str(DOWNLOAD_DIR / f"weekly_departures_{datetime.now().strftime('%Y%m%d')}.pdf")
            download.save_as(departures_pdf)
            logger.info(f"✓ Saved Weekly Departure Report (PDF): {departures_pdf}")
            
            report_page.wait_for_timeout(1000)
            export_btns = report_page.locator("[title='Export']")
            for i in range(export_btns.count()):
                if export_btns.nth(i).is_visible():
                    export_btns.nth(i).click()
                    break
            
            with report_page.expect_download() as download_info:
                report_page.wait_for_timeout(500)
                report_page.click("text=CSV (comma delimited)")
            download = download_info.value
            departures_csv = str(DOWNLOAD_DIR / f"weekly_departures_{datetime.now().strftime('%Y%m%d')}.csv")
            download.save_as(departures_csv)
            logger.info(f"✓ Saved Weekly Departure Report (CSV): {departures_csv}")
            
            report_page.close()
            
            logger.info("=" * 60)
            logger.info("✓ Weekly reports complete!")
            logger.info(f"  - {arrivals_pdf}")
            logger.info(f"  - {arrivals_csv}")
            logger.info(f"  - {departures_pdf}")
            logger.info(f"  - {departures_csv}")
            logger.info("=" * 60)
            
            # Send email
            try:
                from api_email_sender import send_reports
                logger.info("Sending weekly reports via email API...")
                if send_reports(arrivals_pdf, departures_pdf, arrivals_csv, departures_csv, report_type="Weekly"):
                    logger.info("✓ Weekly email sent successfully!")
                else:
                    logger.warning("Email sending failed or not configured.")
            except Exception as e:
                logger.error(f"Email error: {e}")
            
            context.close()
            return True
            
        except Exception as e:
            logger.error(f"Weekly report failed: {e}")
            try:
                page.screenshot(path=f"/opt/paradise-automator/weekly_error_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
            except:
                pass
            context.close()
            return False

if __name__ == "__main__":
    success = run_weekly()
    sys.exit(0 if success else 1)
