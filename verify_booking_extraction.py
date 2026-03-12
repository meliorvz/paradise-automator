#!/usr/bin/env python3
import sys
import logging
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright
from booking_data_extractor import auto_login, extract_bookings

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def verify_single_day_extraction(headless=True):
    """Verify that we can extract data for yesterday."""
    yesterday = datetime.now() - timedelta(days=1)
    date_str = yesterday.strftime("%d/%m/%Y")
    
    logger.info(f"--- VERIFICATION: Extracting bookings for {date_str} ---")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()
        
        try:
            if auto_login(page):
                data = extract_bookings(page, date_str, date_str)
                
                if data:
                    logger.info(f"✅ SUCCESS: Extracted {len(data)} bookings for {date_str}")
                    print("\nSample Data (First Row):")
                    print(data[0])
                else:
                    logger.warning(f"⚠️ No data extracted for {date_str}. This might be expected if there were no departures.")
                    # Try a broader range if zero results to confirm logic
                    logger.info("Attempting a 7-day range to verify logic...")
                    start_str = (yesterday - timedelta(days=7)).strftime("%d/%m/%Y")
                    data = extract_bookings(page, start_str, date_str)
                    if data:
                        logger.info(f"✅ SUCCESS: Extracted {len(data)} bookings for the last 7 days.")
                    else:
                        logger.error("❌ FAILURE: No data extracted even for a 7-day range.")
            else:
                logger.error("❌ FAILURE: Could not log in.")
        except Exception as e:
            logger.error(f"❌ ERROR details: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    headless_mode = "--no-headless" not in sys.argv
    verify_single_day_extraction(headless=headless_mode)
