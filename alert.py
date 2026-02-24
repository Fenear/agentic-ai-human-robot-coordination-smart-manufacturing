"""
alert.py — Alert dispatcher for the HRCA agent.

Supports Slack (incoming webhook) and Email (SMTP).
Configure via environment variables in .env.
"""

import os
import smtplib
from email.mime.text import MIMEText

import requests
from langchain.tools import tool

# ---------------------------------------------------------------------------
# Configuration (loaded from .env via python-dotenv in hrca.py)
# ---------------------------------------------------------------------------
ALERT_METHOD = os.getenv("ALERT_METHOD", "slack")  # "slack" or "email"

# Slack
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")

# Email / SMTP
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _send_slack(message: str) -> str:
    """Post a message to the configured Slack incoming webhook."""
    if not SLACK_WEBHOOK_URL:
        return "ERROR: SLACK_WEBHOOK_URL is not set in .env."

    resp = requests.post(
        SLACK_WEBHOOK_URL,
        json={"text": message},
        timeout=10,
    )
    if resp.status_code == 200:
        return "Slack alert sent successfully."
    return f"Slack error {resp.status_code}: {resp.text}"


def _send_email(message: str) -> str:
    """Send an email alert via SMTP."""
    if not all([SMTP_USER, SMTP_PASSWORD, ALERT_EMAIL_TO]):
        return "ERROR: Email SMTP settings incomplete in .env."

    msg = MIMEText(message)
    msg["Subject"] = "HRCA Safety Alert"
    msg["From"] = SMTP_USER
    msg["To"] = ALERT_EMAIL_TO

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, [ALERT_EMAIL_TO], msg.as_string())
        return "Email alert sent successfully."
    except Exception as exc:
        return f"Email send failed: {exc}"


# ---------------------------------------------------------------------------
# Tool: send_alert
# ---------------------------------------------------------------------------
@tool
def send_alert(message: str) -> str:
    """Send a conflict alert to the shift supervisor via the configured channel.

    Args:
        message: The plain-language alert text (keep it under 3 sentences).

    Returns:
        Confirmation or error message.
    """
    method = ALERT_METHOD.strip().lower()

    if method == "slack":
        return _send_slack(message)
    elif method == "email":
        return _send_email(message)
    else:
        return f"ERROR: Unknown ALERT_METHOD '{method}'. Set to 'slack' or 'email' in .env."
