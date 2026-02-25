"""
alert.py — Alert dispatcher for the HRCA pipeline.

Adapted from v1 alert.py. Supports Slack (incoming webhook) and Email (SMTP).
Configure via environment variables in .env.

Returns bool instead of str to integrate cleanly with pipeline.py.
"""

import os
import smtplib
from email.mime.text import MIMEText

import requests

# Slack
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")

# Email / SMTP
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_EMAIL", os.getenv("SMTP_USER", ""))
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
ALERT_EMAIL_TO = os.getenv("ALERT_RECIPIENT", os.getenv("ALERT_EMAIL_TO", ""))


def _send_slack(message: str) -> bool:
    """Post a message to the configured Slack incoming webhook."""
    if not SLACK_WEBHOOK_URL:
        return False
    resp = requests.post(
        SLACK_WEBHOOK_URL,
        json={"text": message},
        timeout=10,
    )
    return resp.status_code == 200


def _send_email(message: str) -> bool:
    """Send an email alert via SMTP."""
    if not all([SMTP_USER, SMTP_PASSWORD, ALERT_EMAIL_TO]):
        return False
    msg = MIMEText(message)
    msg["Subject"] = "⚠️ HRCA Conflict Alert"
    msg["From"] = SMTP_USER
    msg["To"] = ALERT_EMAIL_TO
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, [ALERT_EMAIL_TO], msg.as_string())
        return True
    except Exception:
        return False


def send_alert(message: str) -> bool:
    """Try Slack first, fall back to email, fall back to UI dashboard."""
    if SLACK_WEBHOOK_URL:
        return _send_slack(message)
    if all([SMTP_USER, SMTP_PASSWORD, ALERT_EMAIL_TO]):
        return _send_email(message)
    # No external channel configured — Streamlit dashboard is the notification
    return True
