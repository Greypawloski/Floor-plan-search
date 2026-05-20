import logging
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from scraper import FloorPlan

log = logging.getLogger(__name__)


def _send(subject: str, html: str, text: str) -> bool:
    smtp_host = os.getenv('SMTP_HOST', '')
    smtp_port = int(os.getenv('SMTP_PORT', '587'))
    smtp_user = os.getenv('SMTP_USER', '')
    smtp_pass = os.getenv('SMTP_PASS', '')
    notify_email = os.getenv('NOTIFY_EMAIL', smtp_user)

    if not all([smtp_host, smtp_user, smtp_pass, notify_email]):
        log.error("SMTP_HOST, SMTP_USER, SMTP_PASS, and NOTIFY_EMAIL must be set.")
        return False

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = smtp_user
    msg['To'] = notify_email
    msg.attach(MIMEText(text, 'plain'))
    msg.attach(MIMEText(html, 'html'))

    log.info("Sending email to %s via SMTP %s:%d...", notify_email, smtp_host, smtp_port)
    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, [notify_email], msg.as_string())
            log.info("Email sent successfully.")
            return True
    except Exception as e:
        log.error("Failed to send email: %s", e, exc_info=True)
    return False


def send_confirmation_email(watch_plans: str, url: str) -> bool:
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
  <p style="color:#555;">You'll get another email the moment one of these plans becomes available.</p>
</body>
</html>"""

    text = (
        f"Floor Plan Monitor is running\n\n"
        f"Watching: {watch_plans}\n"
        f"URL: {url}\n"
        f"Started at: {timestamp}\n\n"
        f"You'll get an email as soon as one of these plans becomes available."
    )

    return _send(subject, html, text)


def send_email_notification(plans: list[FloorPlan], url: str) -> bool:
    count = len(plans)
    subject = (
        f"Floor Plan Available at 7600 Broadway! "
        f"({count} plan{'s' if count > 1 else ''} found)"
    )
    return _send(subject, _build_html(plans, url), _build_text(plans, url))


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
