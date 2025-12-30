#!/usr/bin/env python3
"""
API Email Sender - Integrates with the Comms Centre API.
Documentation: https://comms.paradisestayz.com.au/api/integrations/v1/send
"""

import os
import base64
import requests
import logging
from pathlib import Path
from datetime import date
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Configuration from environment
API_URL = os.getenv("COMMS_API_URL", "https://comms-centre.ancient-fire-eaa9.workers.dev/api/integrations/v1/send")
API_KEY = os.getenv("COMMS_API_KEY", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")  # Comma-separated list


def encode_file_base64(file_path: str) -> str:
    """Read a file and return its base64-encoded content."""
    with open(file_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def get_mime_type(file_path: str) -> str:
    """Get MIME type based on file extension."""
    ext = Path(file_path).suffix.lower()
    mime_types = {
        ".pdf": "application/pdf",
        ".csv": "text/csv",
        ".txt": "text/plain",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }
    return mime_types.get(ext, "application/octet-stream")


def send_email_via_comms_centre(
    subject: str,
    body: str,
    html_body: str,
    attachment_paths: list[str],
    to_emails: list[str] = None
) -> bool:
    """
    Send an email with multiple base64-encoded attachments via Comms Centre API.
    """
    if not API_KEY:
        logger.error("COMMS_API_KEY not configured in .env")
        return False
    
    recipients = to_emails or [e.strip() for e in EMAIL_TO.split(",") if e.strip()]
    if not recipients:
        logger.error("No recipients configured (EMAIL_TO)")
        return False
    
    # Build attachments list according to API spec: { filename, content (base64), contentType }
    attachments = []
    for file_path in attachment_paths:
        if not os.path.exists(file_path):
            logger.warning(f"Attachment not found: {file_path}")
            continue
            
        file_name = Path(file_path).name
        file_content = encode_file_base64(file_path)
        content_type = get_mime_type(file_path)
        
        attachments.append({
            "filename": file_name,
            "content": file_content,
            "contentType": content_type
        })
    
    # Build request payload based on API docs
    payload = {
        "channels": ["email"],
        "to": recipients,
        "subject": subject,
        "body": body,
        "html": html_body,
        "attachments": attachments
    }
    
    headers = {
        "x-integration-key": API_KEY,
        "Content-Type": "application/json"
    }
    
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    try:
        logger.info(f"Triggering Comms Centre API: POST {API_URL}")
        logger.info(f"Targeting {len(recipients)} recipient(s) with {len(attachments)} attachment(s)...")
        
        # Use a session with retry logic for robustness
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["POST"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        
        response = session.post(API_URL, json=payload, headers=headers, timeout=60)
        
        if response.status_code == 200:
            res_json = response.json()
            if res_json.get("success"):
                logger.info("✓ Comms Centre API: Message sent successfully!")
                return True
            else:
                logger.error(f"Comms Centre API error status: {res_json}")
                return False
        elif response.status_code == 405:
            logger.error(f"Comms Centre API error: 405 Method Not Allowed. Is the URL correct? URL: {API_URL}")
            logger.error(f"Allowed methods: {response.headers.get('Allow', 'Not specified')}")
            return False
        else:
            logger.error(f"Comms Centre API error: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"Comms Centre API request failed: {e}")
        return False


def send_daily_reports(arrivals_pdf: str, departures_pdf: str, arrivals_csv: str = None, departures_csv: str = None) -> bool:
    """
    Convenience function to send the daily cleaning reports via Comms Centre.
    """
    import csv
    from datetime import datetime, timedelta
    
    current_time = datetime.now()
    report_date = (current_time + timedelta(days=1))
    date_str = report_date.strftime("%d %b (%A)")  # e.g. 01 Jan (Thursday)
    date_short = report_date.strftime("%d/%m/%Y")
    
    # Helper to parse CSV and get rows
    def parse_csv(file_path):
        data = []
        if not file_path or not os.path.exists(file_path):
            return data
            
        try:
            with open(file_path, "r", encoding="utf-8-sig", errors="replace") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Filter out empty rows or total rows (usually don't have a room number in textBox4)
                    room = row.get("textBox4", "").strip()
                    if room and room.lower() != "total arrivals:" and room.lower() != "daily totals:":
                        data.append({
                            "room": room,
                            "adults": row.get("textBox6", "0"),
                            "children": row.get("textBox7", "0"),
                            "infants": row.get("textBox8", "0"),
                            "name": row.get("textBox2") or row.get("textBox27") or "Guest" # Fallback guess
                        })
        except Exception as e:
            logger.error(f"Failed to parse CSV {file_path}: {e}")
        return data

    # Parse the files
    arrivals_data = parse_csv(arrivals_csv)
    departures_data = parse_csv(departures_csv)
    
    # Generate HTML Tables
    def make_table(title, rows):
        if not rows:
            return f"<p>No {title.lower()} scheduled.</p>"
            
        params = "border: 1px solid #ddd; padding: 8px; text-align: left;"
        html = f"<h3>{title} ({len(rows)})</h3>"
        html += "<table style='border-collapse: collapse; width: 100%; font-family: sans-serif;'>"
        html += f"<tr style='background-color: #f2f2f2;'><th style='{params}'>Room</th><th style='{params}'>Guest</th><th style='{params}'>Pax (A/C/I)</th></tr>"
        
        for r in rows:
            pax = f"{r['adults']}/{r['children']}/{r['infants']}"
            html += f"<tr><td style='{params}'><b>{r['room']}</b></td><td style='{params}'>{r['name']}</td><td style='{params}'>{pax}</td></tr>"
        
        html += "</table>"
        return html

    summary_arr = f"{len(arrivals_data)} checking in"
    summary_dep = f"{len(departures_data)} checking out"
    
    subject = f"Paradise Cleaning {date_str}: {summary_arr}, {summary_dep}"
    
    body = f"""Hi,

Please find attached the cleaning reports for {date_str}.

Summary:
- Arrivals: {summary_arr}
- Departures: {summary_dep}

See the email content for the detailed list.

Automated message from Paradise Automation.
"""

    html_body = f"""
    <div style="font-family: sans-serif; line-height: 1.6; color: #333;">
        <h2 style="color: #2c3e50;">Cleaning Reports for {date_str}</h2>
        
        <div style="margin-bottom: 20px; padding: 15px; background-color: #e8f4fd; border-radius: 5px;">
            <strong>Summary:</strong><br>
            Checking In: <b>{len(arrivals_data)}</b> rooms<br>
            Checking Out: <b>{len(departures_data)}</b> rooms
        </div>

        {make_table("Arrivals", arrivals_data)}
        <br>
        {make_table("Departures", departures_data)}
        
        <hr style="border: 0; border-top: 1px solid #eee; margin: 20px 0;">
        <p style="font-size: 0.9em; color: #777;"><i>Attached: PDF Reports (Official)</i></p>
    </div>
    """
    
    # Attachments: PDFs ONLY
    attachments = []
    for p in [arrivals_pdf, departures_pdf]:
        if p and os.path.exists(p):
            attachments.append(p)
    
    return send_email_via_comms_centre(subject, body, html_body, attachments)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Comms Centre API Integration ready.")
    print(f"Endpoint: {API_URL}")
    print(f"API Key configured: {'YES' if API_KEY else 'NO'}")
    print(f"Recipients: {EMAIL_TO}")
