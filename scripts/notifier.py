"""
Notification Module

Sends email notifications when analyses complete.
Supports SMTP configuration via config.yaml or environment variables.
"""

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


def send_completion_email(
    to_email: str,
    job: Dict[str, Any],
    pdf_path: Optional[str] = None,
    config: Optional[dict] = None,
):
    """Send an email notification when an analysis completes.

    Args:
        to_email: Recipient email address
        job: Job dict with topic, post_count, etc.
        pdf_path: Optional path to PDF report to attach
        config: Optional config dict with SMTP settings
    """
    config = config or {}
    smtp_config = config.get('notifications', {}).get('smtp', {})

    smtp_host = smtp_config.get('host') or os.getenv('SMTP_HOST', '')
    smtp_port = int(smtp_config.get('port') or os.getenv('SMTP_PORT', '587'))
    smtp_user = smtp_config.get('user') or os.getenv('SMTP_USER', '')
    smtp_pass = smtp_config.get('password') or os.getenv('SMTP_PASSWORD', '')
    from_email = smtp_config.get('from') or os.getenv('SMTP_FROM', smtp_user)

    if not smtp_host or not smtp_user:
        logger.info(f"SMTP not configured; skipping email to {to_email}")
        return False

    topic = job.get('topic', 'Unknown Topic')
    post_count = job.get('post_count', 0)
    status = job.get('status', 'complete')

    subject = f"SignalStream: Analysis Complete — {topic}"

    body_html = f"""
    <div style="font-family: -apple-system, sans-serif; max-width: 600px; margin: 0 auto; background: #0C1220; color: #F0F4F8; padding: 2rem; border-radius: 12px;">
        <h1 style="color: #4DA8FF; font-size: 1.3rem; margin-bottom: 1rem;">Analysis Complete</h1>
        <p style="color: #8899B0; font-size: 0.95rem;">Your SignalStream analysis for <strong style="color: #F0F4F8;">"{topic}"</strong> has finished.</p>
        <div style="background: #161E2E; border-radius: 8px; padding: 1rem; margin: 1rem 0;">
            <div style="font-size: 0.85rem; color: #8899B0;">Posts analyzed: <strong style="color: #F0F4F8;">{post_count}</strong></div>
            <div style="font-size: 0.85rem; color: #8899B0;">Status: <strong style="color: #5DD9A5;">{status}</strong></div>
        </div>
        {"<p style='color: #8899B0; font-size: 0.85rem;'>PDF report is attached.</p>" if pdf_path else ""}
        <p style="color: #566580; font-size: 0.75rem; margin-top: 1.5rem;">&mdash; SignalStream</p>
    </div>
    """

    msg = MIMEMultipart()
    msg['From'] = from_email
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body_html, 'html'))

    if pdf_path and Path(pdf_path).exists():
        with open(pdf_path, 'rb') as f:
            pdf_attachment = MIMEApplication(f.read(), _subtype='pdf')
            pdf_attachment.add_header('Content-Disposition', 'attachment', filename=Path(pdf_path).name)
            msg.attach(pdf_attachment)

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        logger.info(f"Completion email sent to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        return False
