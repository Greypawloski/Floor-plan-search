import logging
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from scraper import FloorPlan

log = logging.getLogger(__name__)


def _smtp_connect(host: str, port: int):
    """Return an authenticated-ready SMTP connection. Port 465 uses SSL; others use STARTTLS."""
    if port == 465:
        return smtplib.SMTP_SSL(host, port, timeout=10)
    server = smtplib.SMTP(host, port, timeout=10)
    server.ehlo()
    server.starttls()
    return server


def send_confirmation_email(watch_plans: str, url: str) -> bool:
    smtp_host = os.getenv('SMTP_HOST', 'smtp.gmail.com')
    smtp_port = int(os.getenv('SMTP_PORT', '587'))
    smtp_user = os.getenv('SMTP_USER', '')
    smtp_password = os.getenv('SMTP_PASSWORD', '')
    notify_email = os.getenv('NOTIFY_EMAIL', '')

    if not all([smtp_user, smtp_password, notify_email]):
        log.error("Email config is incomplete — confirmation email not sent.")
        return False

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    subject = "Floor Plan Monitor is running"

    html = f"""<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;max-width:620px;margin:0 auto;padding:24px;color:#333;">
  <h2 style="color:#1565C0;">Monitor is active</h2>
  <p>Your floor plan monitor started successfully and is checking every 5 minutes.</p>
  <table style="border-collapse:collapse;width:100%;margin:16px 0;">
    <tr><td style="padding:8px;color:#888;width:140px;">Watching</td>
        <td style="padding:8px;font-weight:bold;">{watch_plans}</td></tr>
    <tr style="background:#f9f9f9;">
        <td style="padding:8px;color:#888;">URL</td>
        <td style="padding:8px;"><a href="{url}" style="color:#1565C0;">{url}</a></td></tr>
    <tr><td style="padding:8px;color:#888;">Started at</td>
        <td style="padding:8px;">{timestamp}</td></tr>
  </table>
  <p style="color:#555;">You'll get another email as soon as any of these plans become available. No news means nothing is open yet.</p>
</body>
</html>"""

    text = (
        f"Floor Plan Monitor is running\n\n"
        f"Watching: {watch_plans}\n"
        f"URL: {url}\n"
        f"Started at: {timestamp}\n\n"
        f"You'll get an email as soon as one of these plans becomes available."
    )

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = smtp_user
    msg['To'] = notify_email
    msg.attach(MIMEText(text, 'plain'))
    msg.attach(MIMEText(html, 'html'))

    log.info("Connecting to SMTP %s:%s...", smtp_host, smtp_port)
    try:
        with _smtp_connect(smtp_host, smtp_port) as server:
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, [notify_email], msg.as_string())
        log.info("Confirmation email sent to %s", notify_email)
        return True
    except smtplib.SMTPAuthenticationError:
        log.error("SMTP authentication failed — check SMTP_USER and SMTP_PASSWORD.")
    except Exception as e:
        log.error("Failed to send confirmation email: %s", e, exc_info=True)
    return False


def send_email_notification(plans: list[FloorPlan], url: str) -> bool:
    smtp_host = os.getenv('SMTP_HOST', 'smtp.gmail.com')
    smtp_port = int(os.getenv('SMTP_PORT', '587'))
    smtp_user = os.getenv('SMTP_USER', '')
    smtp_password = os.getenv('SMTP_PASSWORD', '')
    notify_email = os.getenv('NOTIFY_EMAIL', '')

    if not all([smtp_user, smtp_password, notify_email]):
        log.error(
            "Email config is incomplete. Set SMTP_USER, SMTP_PASSWORD, and NOTIFY_EMAIL in your .env file."
        )
        return False

    count = len(plans)
    subject = (
        f"🏠 Floor Plan Available at 7600 Broadway! "
        f"({count} plan{'s' if count > 1 else ''} found)"
    )

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = smtp_user
    msg['To'] = notify_email
    msg.attach(MIMEText(_build_text(plans, url), 'plain'))
    msg.attach(MIMEText(_build_html(plans, url), 'html'))

    log.info("Connecting to SMTP %s:%s...", smtp_host, smtp_port)
    try:
        with _smtp_connect(smtp_host, smtp_port) as server:
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, [notify_email], msg.as_string())
        log.info("Email notification sent to %s", notify_email)
        return True
    except smtplib.SMTPAuthenticationError:
        log.error(
            "SMTP authentication failed. For Gmail, use an App Password "
            "(myaccount.google.com/apppasswords) and enable 2FA first."
        )
    except Exception as e:
        log.error("Failed to send email: %s", e, exc_info=True)
    return False


def _build_html(plans: list[FloorPlan], url: str) -> str:
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cards = ''
    for p in plans:
        details_html = p.details.replace('\n', '<br>').replace('<', '&lt;').replace('>', '&gt;')
        cards += f"""
        <div style="background:#f0f8ff;border-left:4px solid #1565C0;padding:14px 18px;
                    margin:12px 0;border-radius:6px;font-family:monospace;font-size:13px;
                    line-height:1.6;">
            <strong style="font-family:Arial,sans-serif;font-size:14px;color:#1565C0;">
                {p.name}
            </strong><br><br>
            {details_html}
        </div>
        """

    return f"""<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;max-width:620px;margin:0 auto;padding:24px;color:#333;">
  <h2 style="color:#1565C0;margin-bottom:4px;">Floor Plan Available!</h2>
  <p style="color:#555;margin-top:0;">
    The following unit(s) at
    <a href="{url}" style="color:#1565C0;">7600 Broadway</a>
    appear to be available:
  </p>
  {cards}
  <p style="margin-top:24px;">
    <a href="{url}"
       style="background:#1565C0;color:white;padding:12px 24px;text-decoration:none;
              border-radius:6px;display:inline-block;font-weight:bold;">
      View Floor Plans &rarr;
    </a>
  </p>
  <p style="color:#aaa;font-size:11px;margin-top:32px;border-top:1px solid #eee;padding-top:12px;">
    Checked at {timestamp} &bull; Floor Plan Availability Monitor
  </p>
</body>
</html>"""


def _build_text(plans: list[FloorPlan], url: str) -> str:
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    sections = '\n\n---\n\n'.join(
        f"{p.name}\n{p.details}" for p in plans
    )
    return (
        f"Floor Plan Available at 7600 Broadway!\n"
        f"{'=' * 40}\n\n"
        f"{sections}\n\n"
        f"View at: {url}\n"
        f"Checked at: {timestamp}\n"
    )
