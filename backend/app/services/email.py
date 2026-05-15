from __future__ import annotations

import asyncio
import html
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


async def _send_email_smtp(to_email: str, subject: str, html_body: str) -> bool:
    if not settings.smtp_host or not settings.smtp_port:
        logger.warning("SMTP not configured. Email not sent.")
        return False

    loop = asyncio.get_running_loop()
    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = settings.smtp_from_email or settings.smtp_username
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(html_body, "html"))

        def _send():
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
                if settings.smtp_tls:
                    server.starttls()
                if settings.smtp_username:
                    server.login(settings.smtp_username, settings.smtp_password)
                server.send_message(msg)

        await loop.run_in_executor(None, _send)
        logger.info("Email sent", extra={"to": to_email, "subject": subject})
        return True
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False


def _log_email(to_email: str, subject: str, body: str) -> None:
    logger.info(
        "--- EMAIL (dev mode) ---\nTo: %s\nSubject: %s\nBody:\n%s\n--- END EMAIL ---",
        to_email, subject, body,
    )


async def send_interview_invitation(
    to_email: str,
    candidate_name: str,
    job_title: str,
    session_id: str,
    base_url: str = "",
) -> bool:
    safe_candidate_name = html.escape(candidate_name or "Candidate")
    safe_job_title = html.escape(job_title or "Position")
    root_url = base_url.rstrip("/")
    interview_link = f"{root_url}/interview/{session_id}" if root_url else f"/interview/{session_id}"
    safe_interview_link = html.escape(interview_link, quote=True)
    subject = f"Official Interview Invitation: {job_title}"

    html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif; background: #f4f7fb; padding: 40px;">
<div style="max-width: 600px; margin: auto; background: white; border-radius: 12px; padding: 32px;">
<div style="text-align: center; margin-bottom: 24px;">
<h1 style="color: #1a56db; font-size: 24px;">AI Recruiter Assistant</h1>
</div>
<h2 style="color: #111827;">Hello {safe_candidate_name},</h2>
<p style="color: #374151; font-size: 16px; line-height: 1.6;">
You have been invited to complete an official interview for the position of
<strong>{safe_job_title}</strong>.
</p>
<p style="color: #374151; font-size: 16px; line-height: 1.6;">
Open the secure interview link below and complete the questions in writing or by voice.
</p>
<div style="text-align: center; margin: 32px 0;">
<a href="{safe_interview_link}"
   style="display: inline-block; padding: 14px 32px; background: #1a56db; color: white;
          text-decoration: none; border-radius: 8px; font-size: 16px; font-weight: bold;">
  Start Your Interview
</a>
</div>
<p style="color: #6b7280; font-size: 14px;">Best of luck!<br>The AI Recruiter Team</p>
</div>
</body>
</html>"""

    if settings.smtp_host:
        return await _send_email_smtp(to_email, subject, html_body)
    _log_email(to_email, subject, html_body)
    return True


async def send_interview_results(
    to_email: str,
    candidate_name: str,
    job_title: str,
    overall_score: float,
    strengths: list[str],
    weaknesses: list[str],
) -> bool:
    subject = f"Interview Results: {job_title}"

    score_pct = f"{overall_score * 100:.1f}%"
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif; background: #f4f7fb; padding: 40px;">
<div style="max-width: 600px; margin: auto; background: white; border-radius: 12px; padding: 32px;">
<h2 style="color: #111827;">Hello {candidate_name},</h2>
<p style="color: #374151;">Your interview for <strong>{job_title}</strong> has been evaluated.</p>
<div style="text-align: center; margin: 24px 0; padding: 24px; background: #eff6ff; border-radius: 8px;">
<p style="font-size: 14px; color: #6b7280;">Overall Score</p>
<p style="font-size: 36px; font-weight: bold; color: #1a56db;">{score_pct}</p>
</div>
<div style="margin: 24px 0;">
<p style="font-weight: bold; color: #059669;">Strengths</p>
<ul style="color: #374151;">{''.join(f'<li>{s}</li>' for s in strengths)}</ul>
</div>
<div style="margin: 24px 0;">
<p style="font-weight: bold; color: #dc2626;">Areas to Improve</p>
<ul style="color: #374151;">{''.join(f'<li>{w}</li>' for w in weaknesses)}</ul>
</div>
</div>
</body>
</html>"""

    if settings.smtp_host:
        return await _send_email_smtp(to_email, subject, html)
    _log_email(to_email, subject, html)
    return True
