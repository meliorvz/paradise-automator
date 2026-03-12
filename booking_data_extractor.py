#!/usr/bin/env python3
import os
import sys
import logging
import csv
import json
import re
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
SEARCH_URL = "https://reimasterapps.com.au/Booking/search?reicid=758"
DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)
MAX_BATCH_DAYS = 62
QUERY_ROW_LIMIT = 1000

# Load env vars (assumes .env in same dir or parent)
from dotenv import load_dotenv
load_dotenv()

REI_USERNAME = os.getenv("REI_USERNAME")
REI_PASSWORD = os.getenv("REI_PASSWORD")


def set_dropdown_value(page, label_text, option_text):
    """Select a value from the Syncfusion dropdown associated with a filter label."""
    filter_root = page.locator(
        f"div.rei-header-filter:has(label.lb-bold:text-is('{label_text}'))"
    ).first
    filter_root.wait_for(state="visible", timeout=20000)
    toggle = filter_root.locator(".e-input-group-icon").first
    toggle.click(force=True)
    page.wait_for_timeout(800)
    option = page.locator(
        f".e-popup-open .e-list-item:text-is('{option_text}'), "
        f".e-popup-open [role='option']:text-is('{option_text}'), "
        f".e-popup-open li:text-is('{option_text}')"
    ).first
    option.click()
    page.wait_for_timeout(800)


def extract_visible_result_rows(page):
    """Read the currently rendered slice of the virtualized ResultGrid."""
    return page.evaluate("""
        () => {
            const normalizeHeader = (text) => {
                return (text || '')
                    .replace(/Press Enter to sort.*$/g, '')
                    .replace(/Press Ctrl space.*$/g, '')
                    .replace(/Press Alt Down.*$/g, '')
                    .replace(/\\s+/g, ' ')
                    .trim();
            };

            const grid = document.querySelector('#ResultGrid');
            if (!grid) {
                return { rows: [], summary: '', scrollHeight: 0, clientHeight: 0 };
            }

            const headers = Array.from(grid.querySelectorAll('th'))
                .map(th => normalizeHeader(th.innerText))
                .filter(Boolean);

            const bodyRows = Array.from(grid.querySelectorAll('.e-content tr'))
                .filter(tr => !tr.classList.contains('e-summaryrow'))
                .filter(tr => tr.querySelectorAll('td').length > 5);

            const rows = bodyRows.map(row => {
                let cells = Array.from(row.querySelectorAll('td'));
                if (cells.length > headers.length) {
                    cells = cells.slice(cells.length - headers.length);
                }

                const rowData = {};
                headers.forEach((header, index) => {
                    if (cells[index]) {
                        rowData[header] = (cells[index].innerText || '').trim();
                    }
                });
                return rowData;
            }).filter(row => Object.keys(row).length > 0 && row['No.'] && row['Status']);

            const content = grid.querySelector('.e-content');
            const summary = Array.from(grid.querySelectorAll('tr.e-summaryrow'))
                .map(row => (row.innerText || '').replace(/\\s+/g, ' ').trim())
                .find(Boolean) || '';

            return {
                rows,
                summary,
                scrollHeight: content ? content.scrollHeight : 0,
                clientHeight: content ? content.clientHeight : 0
            };
        }
    """)


def extract_all_result_rows(page):
    """Walk the virtualized ResultGrid and collect every visible row slice."""
    initial = extract_visible_result_rows(page)
    rows_by_booking = {}

    def merge_rows(rows):
        for row in rows:
            booking_no = row.get("No.")
            if booking_no:
                rows_by_booking[booking_no] = row

    merge_rows(initial["rows"])

    summary_match = re.search(r"(\\d+)\\s+rows", initial.get("summary", ""))
    expected_rows = int(summary_match.group(1)) if summary_match else None
    scroll_height = initial.get("scrollHeight", 0) or 0
    client_height = initial.get("clientHeight", 0) or 0

    if scroll_height and client_height:
        step = 240
        scroll_positions = list(range(0, scroll_height + step, step))
        if scroll_positions[-1] != scroll_height:
            scroll_positions.append(scroll_height)

        for scroll_top in scroll_positions:
            page.eval_on_selector(
                "#ResultGrid .e-content",
                "(el, top) => { el.scrollTop = top; }",
                scroll_top,
            )
            page.wait_for_timeout(350)
            merge_rows(extract_visible_result_rows(page)["rows"])

        if expected_rows and len(rows_by_booking) < expected_rows:
            tighter_step = 120
            scroll_positions = list(range(0, scroll_height + tighter_step, tighter_step))
            if scroll_positions[-1] != scroll_height:
                scroll_positions.append(scroll_height)

            for scroll_top in scroll_positions:
                page.eval_on_selector(
                    "#ResultGrid .e-content",
                    "(el, top) => { el.scrollTop = top; }",
                    scroll_top,
                )
                page.wait_for_timeout(250)
                merge_rows(extract_visible_result_rows(page)["rows"])

    page.eval_on_selector(
        "#ResultGrid .e-content",
        "(el) => { el.scrollTop = 0; }",
    )

    rows = list(rows_by_booking.values())
    logger.info(
        "Collected %s unique rows from virtualized grid%s.",
        len(rows),
        f" (summary reported {expected_rows})" if expected_rows is not None else "",
    )
    return rows, expected_rows

def auto_login(page):
    """Use the same Azure B2C retry pattern that works in the main service."""
    if not REI_USERNAME or not REI_PASSWORD:
        logger.error("No REI credentials configured for booking extraction.")
        return False

    logger.info("Attempting auto-login...")

    page.goto(REI_CLOUD_URL, timeout=60000)

    for attempt in range(1, 3):
        try:
            page.wait_for_timeout(3000)

            current_url = page.url.lower()
            if "reimasterapps.com.au" in current_url and "b2clogin" not in current_url:
                logger.info("✓ Already logged in.")
                return True

            if "login" not in current_url and "b2clogin" not in current_url:
                logger.info("Not on login page after navigation; treating session as authenticated.")
                return True

            logger.info(f"  Login attempt {attempt}/2...")
            page.wait_for_selector("input#email", state="visible", timeout=10000)
            page.fill("input#email", REI_USERNAME)
            page.wait_for_timeout(500)
            page.fill("input#password", REI_PASSWORD)
            page.wait_for_timeout(500)
            page.click("button#next")
            page.wait_for_timeout(5000)
        except Exception as e:
            logger.error(f"Login failed: {e}")
            return False

        current_url = page.url.lower()
        if "reimasterapps.com.au" in current_url and "b2clogin" not in current_url:
            logger.info("✓ Logged in successfully.")
            return True

        error_selectors = [
            ".error.itemLevel",
            ".error.pageLevel",
            "#error",
            ".error-message",
            "[aria-live='polite'].error",
        ]
        for selector in error_selectors:
            try:
                error_elem = page.locator(selector)
                if error_elem.count() > 0 and error_elem.first.is_visible():
                    error_text = (error_elem.first.text_content() or "").strip()
                    if error_text:
                        logger.error(f"Login failed - error shown: {error_text}")
                        return False
            except Exception:
                continue

        logger.info("Still on login page after submit, retrying...")

    logger.warning("Auto-login: max attempts reached, still on login page.")
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

        logger.info(f"Setting filter to {status}...")
        set_dropdown_value(page, "Filters", status)
        set_dropdown_value(page, "Date Mode", "Arrival")

        logger.info(f"Setting dates: {start_date} - {end_date}")
        page.get_by_placeholder("From").fill(start_date)
        page.get_by_placeholder("To").fill(end_date)

        logger.info("Executing search...")
        page.get_by_role("button", name="Search").click()
        page.wait_for_timeout(8000)

        data, expected_rows = extract_all_result_rows(page)
        if expected_rows is not None and len(data) != expected_rows:
            logger.warning(
                "Grid summary reported %s rows but extractor collected %s rows.",
                expected_rows,
                len(data),
            )

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

def load_checkpoint(checkpoint_file):
    if not checkpoint_file or not Path(checkpoint_file).exists():
        return None
    try:
        with open(checkpoint_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Could not load checkpoint {checkpoint_file}: {e}")
        return None


def save_checkpoint(checkpoint_file, next_end_dt, total_rows, completed_batches):
    if not checkpoint_file:
        return
    payload = {
        "next_end_date": next_end_dt.strftime("%d/%m/%Y") if next_end_dt else None,
        "total_rows_written": total_rows,
        "completed_batches": completed_batches,
        "updated_at": datetime.now().isoformat(),
    }
    with open(checkpoint_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def clear_checkpoint(checkpoint_file):
    if checkpoint_file and Path(checkpoint_file).exists():
        Path(checkpoint_file).unlink()


def extract_and_save_range(page, start_dt, end_dt, output_file, status="Departed"):
    s = start_dt.strftime("%d/%m/%Y")
    e = end_dt.strftime("%d/%m/%Y")
    data = extract_bookings(page, s, e, status=status)

    if len(data) >= QUERY_ROW_LIMIT and start_dt < end_dt:
        span_days = (end_dt - start_dt).days
        midpoint = start_dt + timedelta(days=span_days // 2)
        logger.warning(
            f"Range {s} to {e} returned {len(data)} rows; splitting to avoid hitting the query limit."
        )
        left_count = extract_and_save_range(page, start_dt, midpoint, output_file, status=status)
        right_count = extract_and_save_range(page, midpoint + timedelta(days=1), end_dt, output_file, status=status)
        return left_count + right_count

    if len(data) >= QUERY_ROW_LIMIT and start_dt == end_dt:
        logger.warning(
            f"Single-day range {s} returned {len(data)} rows and may still be capped by the UI limit."
        )

    if data:
        save_to_csv(data, output_file)
    return len(data)


def run_historical(
    start_date_str="01/12/2018",
    end_date_str=None,
    output_file="all_bookings_historical.csv",
    checkpoint_file=None,
    resume=False,
):
    """Run extraction from end_date backwards to start_date in 2-month chunks."""
    if end_date_str is None:
        end_date_str = datetime.now().strftime("%d/%m/%Y")
        
    start_dt = datetime.strptime(start_date_str, "%d/%m/%Y")
    end_dt = datetime.strptime(end_date_str, "%d/%m/%Y")

    if start_dt > end_dt:
        raise ValueError("Historical extraction start date must be on or before end date.")

    if checkpoint_file is None:
        checkpoint_file = f"{output_file}.progress.json"

    total_rows = 0
    completed_batches = 0
    current_end = end_dt

    if resume:
        checkpoint = load_checkpoint(checkpoint_file)
        if checkpoint and checkpoint.get("next_end_date"):
            current_end = datetime.strptime(checkpoint["next_end_date"], "%d/%m/%Y")
            total_rows = checkpoint.get("total_rows_written", 0)
            completed_batches = checkpoint.get("completed_batches", 0)
            logger.info(
                f"Resuming historical extraction from {current_end.strftime('%d/%m/%Y')} "
                f"using checkpoint {checkpoint_file}"
            )
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(viewport={"width": 1800, "height": 1400})
        page = context.new_page()
        
        if auto_login(page):
            while current_end >= start_dt:
                current_start = current_end - timedelta(days=MAX_BATCH_DAYS)
                if current_start < start_dt:
                    current_start = start_dt

                s = current_start.strftime("%d/%m/%Y")
                e = current_end.strftime("%d/%m/%Y")
                
                logger.info(f"--- Processing Batch: {s} to {e} ---")
                batch_rows = extract_and_save_range(
                    page,
                    current_start,
                    current_end,
                    output_file,
                    status="Departed",
                )
                total_rows += batch_rows
                completed_batches += 1
                logger.info(
                    f"Completed batch {completed_batches}: {s} to {e} "
                    f"({batch_rows} rows, cumulative {total_rows})"
                )
                
                # Move to the previous period.
                current_end = current_start - timedelta(days=1)
                save_checkpoint(checkpoint_file, current_end, total_rows, completed_batches)
                page.wait_for_timeout(2000)
                
        browser.close()

    clear_checkpoint(checkpoint_file)

def run_daily_maintenance():
    """Extract bookings for yesterday and today to ensure everything is captured."""
    today = datetime.now()
    yesterday = today - timedelta(days=1)
    
    s = yesterday.strftime("%d/%m/%Y")
    e = today.strftime("%d/%m/%Y")
    
    output_file = "all_bookings_historical.csv"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(viewport={"width": 1800, "height": 1400})
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
    parser.add_argument("--end", help="End date (DD/MM/YYYY) for historical run")
    parser.add_argument("--output", default="all_bookings_historical.csv", help="Output CSV path")
    parser.add_argument("--checkpoint", help="Checkpoint JSON path")
    parser.add_argument("--resume", action="store_true", help="Resume historical extraction from checkpoint")
    
    args = parser.parse_args()
    
    if args.historical:
        start = args.start if args.start else "01/12/2018"
        run_historical(start, args.end, args.output, args.checkpoint, args.resume)
    elif args.maintenance:
        run_daily_maintenance()
    else:
        parser.print_help()
