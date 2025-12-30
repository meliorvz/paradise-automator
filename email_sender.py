#!/usr/bin/env python3
"""
Email utility for sending PDF attachments via Gmail SMTP.
Uses environment variables for credentials (never hardcode passwords!).
"""

import os
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# Email configuration from environment variables
EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_TO = os.getenv("EMAIL_TO")  # Comma-separated list


def send_email_with_attachment(
    pdf_path: str,
    filename: str | None = None,
    subject: str = "Daily Cleaning Report",
    body: str = "Please find attached the daily cleaning report."
) -> bool:
    """
    Send an email with a PDF attachment.
    
    Args:
        pdf_path: Path to the PDF file to attach.
        filename: Filename for the attachment (defaults to original filename).
        subject: Email subject line.
        body: Email body text.
    
    Returns:
        True if email sent successfully, False otherwise.
    """
    # Validate configuration
    if not all([EMAIL_FROM, EMAIL_PASSWORD, EMAIL_TO]):
        logger.error(
            "Email not configured. Set EMAIL_FROM, EMAIL_PASSWORD, and EMAIL_TO "
            "in your .env file."
        )
        return False
    
    # Validate file exists
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        logger.error(f"PDF file not found: {pdf_path}")
        return False
    
    if filename is None:
        filename = pdf_path.name
    
    try:
        # Create message
        msg = MIMEMultipart()
        msg["From"] = EMAIL_FROM
        msg["To"] = EMAIL_TO
        msg["Subject"] = subject
        
        # Add body
        msg.attach(MIMEText(body, "plain"))
        
        # Attach PDF
        with open(pdf_path, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f"attachment; filename={filename}"
            )
            msg.attach(part)
        
        # Send email
        logger.info(f"Sending email to {EMAIL_TO}...")
        
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.send_message(msg)
        
        logger.info("Email sent successfully")
        return True
        
    except smtplib.SMTPAuthenticationError:
        logger.error(
            "Gmail authentication failed. Make sure you're using an App Password, "
            "not your main password. Create one at: https://myaccount.google.com/apppasswords"
        )
        return False
        
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False


# Allow running directly for testing
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python email_sender.py <path_to_pdf>")
        sys.exit(1)
    
    logging.basicConfig(level=logging.INFO)
    success = send_email_with_attachment(sys.argv[1])
    sys.exit(0 if success else 1)
