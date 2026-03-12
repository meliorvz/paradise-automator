#!/usr/bin/env python3
import os
import sys
import logging
import csv
from datetime import datetime, timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("booking_extraction.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Constants
REI_CLOUD_URL = "https://reimasterapps.com.au/Customers/Dashboard?reicid=758"
SEARCH_URL = "https://reimasterapps.com.au/Booking/BookingSearch?reicid=758"
DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

# Load env vars (assumes .env in same dir or parent)
from dotenv import load_dotenv
load_dotenv()

REI_USERNAME = os.getenv("REI_USERNAME")
REI_PASSWORD = os.getenv("REI_PASSWORD")

def auto_login(page):
    """Reuse login logic from main script or implement locally."""
    logger.info("Attempting auto-login...")
    page.goto(REI_CLOUD_URL)
    
    if "login" in page.url.lower() or "b2clogin" in page.url.lower():
        try:
            page.wait_for_selector("input#email", state="visible", timeout=10000)
            page.fill("input#email", REI_USERNAME)
            page.fill("input#password", REI_PASSWORD)
            page.click("button#next")
            page.wait_for_timeout(5000)
        except Exception as e:
            logger.error(f"Login failed: {e}")
            return False
    
    if "reimasterapps.com.au" in page.url.lower() and "login" not in page.url.lower():
        logger.info("✓ Logged in successfully.")
        return True
    return False

def extract_bookings(page, start_date, end_date, status="Departed"):
    """
    Extracts bookings for a specific date range and status.
    Dates should be strings in DD/MM/YYYY format.
    """
    logger.info(f"Extracting bookings from {start_date} to {end_date} (Status: {status})...")
    
    try:
        page.goto(SEARCH_URL, timeout=60000)
        page.wait_for_load_state("networkidle")
        
        # 3. Set Booking Filter
        logger.info(f"Setting filter to {status}...")
        # Often these are Kendo dropdowns that look like spans
        try:
            # Try to find the filter label and click the dropdown near it
            page.click(".k-dropdown-wrap", timeout=5000)
            page.wait_for_selector(".k-list-container:visible")
            page.click(f".k-list-container li:has-text('{status}')")
        except Exception as e:
            logger.warning(f"Dropdown click failed, trying alternative: {e}")
            page.click(f"text={status}") # Fallback to clicking text if visible

        # 4. Enable Advanced (optional but part of flow)
        try:
            advanced_btn = page.locator("button:has-text('Advanced'), .btn-advanced")
            if advanced_btn.count() > 0:
                advanced_btn.click()
                page.wait_for_timeout(500)
        except:
            pass

        # 5. Select All Data Columns
        logger.info("Selecting all columns...")
        # The user says "Columns" dropdown button on the far right
        try:
            page.click("button:has-text('Columns')", timeout=5000)
            page.wait_for_selector(".k-column-chooser-item, .modal-content", state="visible")
            
            # Look for "Select All" checkbox/label
            select_all = page.locator("label:has-text('Select All'), input[type='checkbox']:near(label:has-text('Select All'))").first
            if not select_all.is_checked():
                select_all.click()
            
            page.click("button:has-text('Ok'), .btn-primary:has-text('Ok')")
            page.wait_for_timeout(1000)
        except Exception as e:
            logger.warning(f"Column selection failed: {e}")

        # 6. Input Date Range
        logger.info(f"Setting dates: {start_date} - {end_date}")
        # The IDs are often FromDate and ToDate
        page.fill("#FromDate, [name='FromDate'], input[data-role='datepicker']:nth-of-type(1)", start_date)
        page.fill("#ToDate, [name='ToDate'], input[data-role='datepicker']:nth-of-type(2)", end_date)
        
        # 7. Execute Search
        logger.info("Executing search...")
        # User says primary blue Search button with magnifying glass
        page.click("button#btnSearch, button:has-text('Search')")
        
        # Wait for grid to update
        page.wait_for_selector(".k-loading-mask", state="hidden", timeout=30000)
        page.wait_for_timeout(3000) # Give data time to render

        # 8. Extract Data
        # We look for the main grid container
        grid_selector = ".k-grid"
        page.wait_for_selector(grid_selector)
        
        # Use page.evaluate to extract data compactly
        data = page.evaluate("""
            () => {
                const headers = Array.from(document.querySelectorAll('.k-grid-header th'))
                    .map(th => th.innerText.trim())
                    .filter(h => h !== "");
                
                const rows = Array.from(document.querySelectorAll('.k-grid-content tr'));
                return rows.map(row => {
                    const cells = Array.from(row.querySelectorAll('td'));
                    const rowData = {};
                    headers.forEach((header, index) => {
                        if (cells[index]) {
                            rowData[header] = cells[index].innerText.trim();
                        }
                    });
                    return rowData;
                }).filter(row => Object.keys(row).length > 0);
            }
        """)
        
        logger.info(f"✓ Extracted {len(data)} rows.")
        return data

    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        try:
            page.screenshot(path=f"extraction_error_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        except:
            pass
        return []

def save_to_csv(data, filename):
    if not data:
        return
    
    file_path = Path(filename)
    file_exists = file_path.exists()
    
    # Ensure all data has the same keys (headers)
    keys = data[0].keys()
    
    with open(filename, 'a' if file_exists else 'w', newline='', encoding='utf-8') as f:
        dict_writer = csv.DictWriter(f, fieldnames=keys)
        if not file_exists:
            dict_writer.writeheader()
        dict_writer.writerows(data)
    logger.info(f"✓ Added {len(data)} rows to {filename}")

def run_historical(start_date_str="01/12/2018", end_date_str=None):
    """Run extraction desde 01/12/2018 to now in 2-month chunks."""
    if end_date_str is None:
        end_date_str = datetime.now().strftime("%d/%m/%Y")
        
    start_dt = datetime.strptime(start_date_str, "%d/%m/%Y")
    end_dt = datetime.strptime(end_date_str, "%d/%m/%Y")
    
    output_file = "all_bookings_historical.csv"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        
        if auto_login(page):
            current_start = start_dt
            while current_start < end_dt:
                # 2 months chunk
                current_end = current_start + timedelta(days=62)
                if current_end > end_dt:
                    current_end = end_dt
                
                s = current_start.strftime("%d/%m/%Y")
                e = current_end.strftime("%d/%m/%Y")
                
                logger.info(f"--- Processing Batch: {s} to {e} ---")
                data = extract_bookings(page, s, e)
                if data:
                    save_to_csv(data, output_file)
                
                # Move to next period
                current_start = current_end + timedelta(days=1)
                page.wait_for_timeout(2000) # Anti-throttle
                
        browser.close()

def run_daily_maintenance():
    """Extract bookings for yesterday and today to ensure everything is captured."""
    today = datetime.now()
    yesterday = today - timedelta(days=1)
    
    s = yesterday.strftime("%d/%m/%Y")
    e = today.strftime("%d/%m/%Y")
    
    output_file = "all_bookings_historical.csv"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        
        if auto_login(page):
            logger.info("Running daily maintenance...")
            data = extract_bookings(page, s, e)
            if data:
                # In a real maintenance task, you might want to de-duplicate 
                # or just append and clean later. For now, we append.
                save_to_csv(data, output_file)
                
        browser.close()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="REI Cloud Booking Extractor")
    parser.add_argument("--historical", action="store_true", help="Run full historical extraction")
    parser.add_argument("--maintenance", action="store_true", help="Run daily maintenance extraction")
    parser.add_argument("--start", help="Start date (DD/MM/YYYY) for historical run")
    
    args = parser.parse_args()
    
    if args.historical:
        start = args.start if args.start else "01/12/2018"
        run_historical(start)
    elif args.maintenance:
        run_daily_maintenance()
    else:
        parser.print_help()
