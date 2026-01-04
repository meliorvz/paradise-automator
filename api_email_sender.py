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
API_URL = os.getenv("COMMS_API_URL", "https://comms-centre-prod.ancient-fire-eaa9.workers.dev/api/integrations/v1/send")
API_KEY = os.getenv("COMMS_API_KEY", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")  # Comma-separated list
EMAIL_CC = os.getenv("EMAIL_CC", "")  # Comma-separated CC list
SMS_SENDER_NOTIFY = os.getenv("SMS_SENDER_NOTIFY", "")  # E164 format
ESCALATION_PHONE = os.getenv("ESCALATION_PHONE", "+61402526638")  # Default from user
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")  # Numeric Telegram Chat ID


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
    
    # Add CC if configured
    cc_list = [e.strip() for e in EMAIL_CC.split(",") if e.strip()]
    if cc_list:
        payload["cc"] = cc_list
    
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


def parse_csv(file_path: str) -> list[dict]:
    """Helper to parse CSV and get rows."""
    import csv
    data = []
    if not file_path or not os.path.exists(file_path):
        return data
        
    try:
        with open(file_path, "r", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Filter out empty rows or total/header rows
                # Correct mapping: TrnReference1 is the Room ID, textBox4 is the Booking Number
                room = row.get("TrnReference1", "").strip()
                booking_ref = row.get("textBox4", "").strip()
                date_str = row.get("textBox2", "").strip()  # e.g. "Sunday, 4 January 2026"
                
                if room and room.lower() not in ["total arrivals:", "total departures:", "daily totals:", "", "room"]:
                    # Filter out BONDREFUND entries (cancelled bookings, refund placeholders)
                    if "BONDREFUND" in room.upper():
                        continue
                    # Verify it's a real room number (starts with digit or letter for named rooms)
                    first_char = room.replace(" ", "").replace("-", "")[:1]
                    if first_char.isalnum():
                        data.append({
                            "room": room,
                            "booking_ref": booking_ref,
                            "room_type": row.get("textBox16", "").strip(),
                            "adults": row.get("textBox6", "0"),
                            "children": row.get("textBox7", "0"),
                            "infants": row.get("textBox8", "0"),
                            "time": row.get("textBox10", "").strip(),
                            "name": row.get("textBox19", "").strip() or "Guest",
                            "date": date_str
                        })
    except Exception as e:
        logger.error(f"Failed to parse CSV {file_path}: {e}")
    return data


def parse_csv_by_date(file_path: str) -> dict:
    """
    Parse CSV and group entries by date, sorted chronologically (nearest first).
    Returns: { 'Sunday, 4 January 2026': [entries...], ... }
    """
    from datetime import datetime
    from collections import defaultdict
    
    entries = parse_csv(file_path)
    by_date = defaultdict(list)
    
    for entry in entries:
        date_str = entry.get("date", "Unknown")
        by_date[date_str].append(entry)
    
    # Sort dates chronologically (nearest first)
    def parse_date(date_str):
        """Parse date string like 'Sunday, 4 January 2026' to datetime."""
        try:
            # Remove day name prefix
            if ", " in date_str:
                date_str = date_str.split(", ", 1)[1]
            return datetime.strptime(date_str, "%d %B %Y")
        except:
            return datetime.max  # Unknown dates go to end
    
    sorted_dates = sorted(by_date.keys(), key=parse_date)
    
    return {date: by_date[date] for date in sorted_dates}

def send_reports(arrivals_pdf: str, departures_pdf: str, arrivals_csv: str = None, departures_csv: str = None, report_type: str = "Daily") -> bool:
    """
    Convenience function to send the cleaning reports via Comms Centre.
    report_type: 'Daily' or 'Weekly'
    """
    import csv
    from datetime import datetime, timedelta
    
    current_time = datetime.now()
    
    if report_type == "Weekly":
        # Next 7 days
        start_date = current_time.date()
        end_date = start_date + timedelta(days=6)
        date_str = f"{start_date.strftime('%d %b')} - {end_date.strftime('%d %b')}"
        date_title = f"Next 7 Days ({date_str})"
    else:
        # Tomorrow (default)
        report_date = (current_time + timedelta(days=1))
        date_str = report_date.strftime("%d %b (%A)")  # e.g. 01 Jan (Thursday)
        date_title = f"{date_str}"
    
    # Parse the files
    arrivals_data = parse_csv(arrivals_csv)
    departures_data = parse_csv(departures_csv)
    
    # Generate HTML Tables with time column and room type
    def make_table(title, rows, time_label="Time"):
        if not rows:
            return f"<p>No {title.lower()} scheduled.</p>"
            
        params = "border: 1px solid #ddd; padding: 8px; text-align: left; vertical-align: top;"
        html = f"<h3>{title} ({len(rows)})</h3>"
        html += "<table style='border-collapse: collapse; width: 100%; font-family: sans-serif;'>"
        html += f"<tr style='background-color: #f2f2f2;'><th style='{params}'>Room</th><th style='{params}'>Type</th><th style='{params}'>Guest</th><th style='{params}'>Guests</th><th style='{params}'>{time_label}</th></tr>"
        
        for r in rows:
            pax_lines = f"{r['adults']} adults<br>{r['children']} children<br>{r['infants']} infants"
            time_val = r.get('time', '') or '-'
            room_type = r.get('room_type', '') or '-'
            
            html += f"<tr><td style='{params}'><b>{r['room']}</b></td><td style='{params}'>{room_type}</td><td style='{params}'>{r['name']}</td><td style='{params}'>{pax_lines}</td><td style='{params}'><b>{time_val}</b></td></tr>"
        
        html += "</table>"
        return html

    summary_arr = f"{len(arrivals_data)} checking in"
    summary_dep = f"{len(departures_data)} checking out"
    
    if report_type == "Weekly":
        subject = f"Weekly Cleaning Report {date_str}: {summary_arr}, {summary_dep}"
        intro_text = f"Please find attached the weekly cleaning reports for {date_str}."
        header_text = f"Weekly Cleaning Schedule ({date_str})"
        
        # Group data by date for weekly reports
        arrivals_by_date = parse_csv_by_date(arrivals_csv)
        departures_by_date = parse_csv_by_date(departures_csv)
        
        # Get all unique dates and sort them
        all_dates = sorted(
            set(arrivals_by_date.keys()) | set(departures_by_date.keys()),
            key=lambda d: datetime.strptime(d.split(", ", 1)[1], "%d %B %Y") if ", " in d else datetime.max
        )
        
        # Build summary table for top of email
        summary_table_html = """
        <h3>📅 Weekly Overview</h3>
        <table style='border-collapse: collapse; width: 100%; font-family: sans-serif; margin-bottom: 20px;'>
            <tr style='background-color: #2c3e50; color: white;'>
                <th style='border: 1px solid #ddd; padding: 10px; text-align: left;'>Day</th>
                <th style='border: 1px solid #ddd; padding: 10px; text-align: left;'>Date</th>
                <th style='border: 1px solid #ddd; padding: 10px; text-align: center;'>Check-Ins</th>
                <th style='border: 1px solid #ddd; padding: 10px; text-align: center;'>Check-Outs</th>
            </tr>
        """
        
        total_arr = 0
        total_dep = 0
        for date_full in all_dates:
            arr_count = len(arrivals_by_date.get(date_full, []))
            dep_count = len(departures_by_date.get(date_full, []))
            total_arr += arr_count
            total_dep += dep_count
            
            # Parse day name and date
            parts = date_full.split(", ", 1)
            day_name = parts[0] if len(parts) > 1 else ""
            date_part = parts[1] if len(parts) > 1 else date_full
            
            summary_table_html += f"""
            <tr>
                <td style='border: 1px solid #ddd; padding: 8px;'><b>{day_name}</b></td>
                <td style='border: 1px solid #ddd; padding: 8px;'>{date_part}</td>
                <td style='border: 1px solid #ddd; padding: 8px; text-align: center; color: #27ae60;'><b>{arr_count}</b></td>
                <td style='border: 1px solid #ddd; padding: 8px; text-align: center; color: #e74c3c;'><b>{dep_count}</b></td>
            </tr>
            """
        
        # Add totals row
        summary_table_html += f"""
            <tr style='background-color: #f8f9fa; font-weight: bold;'>
                <td colspan='2' style='border: 1px solid #ddd; padding: 10px; text-align: right;'>TOTAL</td>
                <td style='border: 1px solid #ddd; padding: 10px; text-align: center; color: #27ae60;'>{total_arr}</td>
                <td style='border: 1px solid #ddd; padding: 10px; text-align: center; color: #e74c3c;'>{total_dep}</td>
            </tr>
        </table>
        """
        
        # Build day-by-day sections
        day_sections_html = ""
        params = "border: 1px solid #ddd; padding: 8px; text-align: left; vertical-align: top;"
        
        for date_full in all_dates:
            day_arrivals = arrivals_by_date.get(date_full, [])
            day_departures = departures_by_date.get(date_full, [])
            
            day_sections_html += f"""
            <div style='margin: 20px 0; padding: 15px; background-color: #f8f9fa; border-radius: 8px; border-left: 4px solid #3498db;'>
                <h3 style='margin: 0 0 10px 0; color: #2c3e50;'>📆 {date_full}</h3>
                <p style='margin: 0 0 15px 0; color: #666;'>
                    <span style='color: #27ae60;'><b>{len(day_arrivals)}</b> Check-Ins</span> &nbsp;|&nbsp; 
                    <span style='color: #e74c3c;'><b>{len(day_departures)}</b> Check-Outs</span>
                </p>
            """
            
            # Arrivals table for this day
            if day_arrivals:
                day_sections_html += f"""
                <h4 style='margin: 10px 0 5px 0; color: #27ae60;'>Arrivals</h4>
                <table style='border-collapse: collapse; width: 100%; font-family: sans-serif; margin-bottom: 15px;'>
                    <tr style='background-color: #27ae60; color: white;'>
                        <th style='{params}'>Room</th>
                        <th style='{params}'>Type</th>
                        <th style='{params}'>Guest</th>
                        <th style='{params}'>Guests</th>
                    </tr>
                """
                for r in day_arrivals:
                    pax = f"{r['adults']}A / {r['children']}C / {r['infants']}I"
                    day_sections_html += f"""
                    <tr>
                        <td style='{params}'><b>{r['room']}</b></td>
                        <td style='{params}'>{r.get('room_type', '-')}</td>
                        <td style='{params}'>{r['name']}</td>
                        <td style='{params}'>{pax}</td>
                    </tr>
                    """
                day_sections_html += "</table>"
            else:
                day_sections_html += "<p style='color: #999; font-style: italic;'>No arrivals</p>"
            
            # Departures table for this day
            if day_departures:
                day_sections_html += f"""
                <h4 style='margin: 10px 0 5px 0; color: #e74c3c;'>Departures</h4>
                <table style='border-collapse: collapse; width: 100%; font-family: sans-serif;'>
                    <tr style='background-color: #e74c3c; color: white;'>
                        <th style='{params}'>Room</th>
                        <th style='{params}'>Type</th>
                        <th style='{params}'>Guest</th>
                        <th style='{params}'>Guests</th>
                    </tr>
                """
                for r in day_departures:
                    pax = f"{r['adults']}A / {r['children']}C / {r['infants']}I"
                    day_sections_html += f"""
                    <tr>
                        <td style='{params}'><b>{r['room']}</b></td>
                        <td style='{params}'>{r.get('room_type', '-')}</td>
                        <td style='{params}'>{r['name']}</td>
                        <td style='{params}'>{pax}</td>
                    </tr>
                    """
                day_sections_html += "</table>"
            else:
                day_sections_html += "<p style='color: #999; font-style: italic;'>No departures</p>"
            
            day_sections_html += "</div>"
        
        html_body = f"""
        <div style="font-family: sans-serif; line-height: 1.6; color: #333;">
            <h2 style="color: #2c3e50;">{header_text}</h2>
            
            {summary_table_html}
            
            <hr style="border: 0; border-top: 2px solid #3498db; margin: 25px 0;">
            
            <h2 style="color: #2c3e50;">📋 Day-by-Day Details</h2>
            {day_sections_html}
            
            <hr style="border: 0; border-top: 1px solid #eee; margin: 20px 0;">
            <p style="font-size: 0.9em; color: #777;"><i>Attached: PDF Reports (Official)</i></p>
        </div>
        """
    else:
        subject = f"Tomorrow's Cleaning {date_str}: {summary_arr}, {summary_dep}"
        intro_text = f"Please find attached the cleaning reports for {date_str}."
        header_text = f"Cleaning Reports for {date_str}"
        
        html_body = f"""
        <div style="font-family: sans-serif; line-height: 1.6; color: #333;">
            <h2 style="color: #2c3e50;">{header_text}</h2>
            
            <div style="margin-bottom: 20px; padding: 15px; background-color: #e8f4fd; border-radius: 5px;">
                <strong>Summary:</strong><br>
                Checking In: <b>{len(arrivals_data)}</b> rooms<br>
                Checking Out: <b>{len(departures_data)}</b> rooms
            </div>

            {make_table("Arrivals", arrivals_data, time_label="Check-in")}
            <br>
            {make_table("Departures", departures_data, time_label="Check-out")}
            
            <hr style="border: 0; border-top: 1px solid #eee; margin: 20px 0;">
            <p style="font-size: 0.9em; color: #777;"><i>Attached: PDF Reports (Official)</i></p>
        </div>
        """
    
    body = f"""Hi,

{intro_text}

Summary:
- Arrivals: {summary_arr}
- Departures: {summary_dep}

See the email content for the detailed list.

"""
    
    # Attachments: PDFs ONLY
    attachments = []
    for p in [arrivals_pdf, departures_pdf]:
        if p and os.path.exists(p):
            attachments.append(p)
    
    # === STEP 1: Send Email to Recipients ===
    email_success = send_email_via_comms_centre(subject, body, html_body, attachments)
    
    # === STEP 2: SMS Summary to Sender (if configured) ===
    sms_success = False
    if SMS_SENDER_NOTIFY:
        sms_body = f"{report_type} Cleaning {date_str}: {summary_arr}, {summary_dep}. Check email."
        sms_success = send_sms_notification(SMS_SENDER_NOTIFY, sms_body)
    
    # === STEP 3: Telegram Delivery Report ===
    telegram_report = f"📊 {report_type} Report Delivery for {date_str}:\n"
    telegram_report += f"• Email: {'✅ Sent' if email_success else '❌ FAILED'}\n"
    if SMS_SENDER_NOTIFY:
        telegram_report += f"• SMS to Sender: {'✅ Sent' if sms_success else '❌ FAILED'}\n"
    telegram_report += f"\nSummary: {summary_arr}, {summary_dep}"
    send_telegram_notification(telegram_report)
    
    # === STEP 4: Escalation if email failed ===
    if not email_success:
        send_failure_alert(f"Email delivery FAILED for {date_str}. Check server logs.")
    
    return email_success


def send_sms_notification(to_phone: str, message: str) -> bool:
    """Send an SMS notification."""
    if not API_KEY:
        logger.error("API key not configured for SMS")
        return False
        
    payload = {
        "channels": ["sms"],
        "to": [to_phone],
        "body": message
    }
    
    headers = {
        "x-integration-key": API_KEY,
        "Content-Type": "application/json"
    }
    
    try:
        logger.info(f"Sending SMS to {to_phone}...")
        response = requests.post(API_URL, json=payload, headers=headers, timeout=30)
        if response.status_code == 200 and response.json().get("success"):
            logger.info("✓ SMS sent successfully")
            return True
        else:
            logger.error(f"SMS failed: {response.text}")
            return False
    except Exception as e:
        logger.error(f"SMS error: {e}")
        return False


def send_telegram_notification(message: str) -> bool:
    """Send a Telegram notification (uses default integration recipients)."""
    if not API_KEY:
        logger.error("API key not configured for Telegram")
        return False
    
    if not TELEGRAM_CHAT_ID:
        logger.warning("TELEGRAM_CHAT_ID not configured, skipping Telegram notification")
        return False
        
    payload = {
        "channels": ["telegram"],
        "to": [TELEGRAM_CHAT_ID],
        "body": message
    }
    
    headers = {
        "x-integration-key": API_KEY,
        "Content-Type": "application/json"
    }
    
    try:
        logger.info("Sending Telegram notification...")
        response = requests.post(API_URL, json=payload, headers=headers, timeout=30)
        if response.status_code == 200 and response.json().get("success"):
            logger.info("✓ Telegram notification sent")
            return True
        else:
            logger.error(f"Telegram failed: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Telegram error: {e}")
        return False


def send_failure_alert(error_message: str) -> bool:
    """
    Send an urgent failure notification via SMS and Telegram.
    """
    if not API_KEY:
        logger.error("COMMS_API_KEY not configured")
        return False

    subject = "🚨 CRITICAL: REI Automation FAILED"
    body = f"URGENT: The REI Automation script failed to run.\n\nError: {error_message}\n\nPlease check the server immediately."
    
    # User requested SMS to specific number + Telegram
    # Assuming Telegram uses default integration recipients if no numeric ID provided
    recipients = [ESCALATION_PHONE]
    
    payload = {
        "channels": ["sms", "telegram"],
        "to": recipients,
        "body": body
    }
    
    headers = {
        "x-integration-key": API_KEY,
        "Content-Type": "application/json"
    }
    
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    try:
        logger.warning(f"Sending FAILURE ALERT to {recipients} via SMS/Telegram...")
        
        session = requests.Session()
        retry = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
        session.mount("https://", HTTPAdapter(max_retries=retry))
        
        response = session.post(API_URL, json=payload, headers=headers, timeout=30)
        
        if response.status_code == 200 and response.json().get("success"):
            logger.info("✓ Failure alert sent successfully.")
            return True
        else:
            logger.error(f"Failed to send failure alert: {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"Error sending failure alert: {e}")
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Comms Centre API Integration ready.")
    print(f"Endpoint: {API_URL}")
    print(f"API Key configured: {'YES' if API_KEY else 'NO'}")
    print(f"Recipients: {EMAIL_TO}")
