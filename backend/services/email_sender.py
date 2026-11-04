"""
Email sender service using Gmail SMTP.
Sends emails with optional resume attachment.
"""
import json
import os
import smtplib
import logging
from email.message import EmailMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from typing import Optional

from config import settings

logger = logging.getLogger("EmailSender")


def _attachment_name(path: str) -> str:
    """Filename the recipient sees for the resume attachment.

    Uploaded resumes are all stored at settings.resume_path, so the on-disk name
    is a generic "resume.pdf". The sidecar written by the resume router keeps the
    name the user actually uploaded — send that instead when it is available.
    (Read here rather than imported from the router: services must not depend on
    the API layer.)
    """
    if path == settings.resume_path:
        try:
            with open(settings.resume_meta_path, encoding="utf-8") as f:
                original = json.load(f).get("original_filename")
            if original:
                return os.path.basename(original)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass
    return os.path.basename(path)


class EmailSender:
    """Send emails via Gmail SMTP with optional attachments."""

    def __init__(self):
        self.smtp_host = settings.gmail_smtp_host
        self.smtp_port = settings.gmail_smtp_port
        self.sender_email = settings.gmail_email
        self.app_password = settings.gmail_app_password

    def _validate_config(self):
        """Check that Gmail credentials are configured."""
        if not self.sender_email or not self.app_password:
            raise ValueError(
                "Gmail credentials not configured. "
                "Set GMAIL_EMAIL and GMAIL_APP_PASSWORD in .env file."
            )

    def send_email(
        self,
        recipient: str,
        subject: str,
        body: str,
        attach_resume: bool = False,
        resume_path: Optional[str] = None,
    ) -> dict:
        """
        Send a single email.

        Returns:
            dict with 'success' (bool) and 'error' (str or None)
        """
        self._validate_config()

        try:
            # Create message
            msg = MIMEMultipart()
            msg["From"] = self.sender_email
            msg["To"] = recipient
            msg["Subject"] = subject

            # Attach HTML body
            msg.attach(MIMEText(body, "html"))

            # Attach resume if requested
            if attach_resume:
                r_path = resume_path or settings.resume_path
                if os.path.exists(r_path):
                    with open(r_path, "rb") as f:
                        attachment = MIMEBase("application", "octet-stream")
                        attachment.set_payload(f.read())
                        encoders.encode_base64(attachment)
                        filename = _attachment_name(r_path)
                        attachment.add_header(
                            "Content-Disposition",
                            "attachment",
                            filename=filename,
                        )
                        msg.attach(attachment)
                    logger.info(f"Resume attached: {r_path}")
                else:
                    logger.warning(f"Resume file not found: {r_path}")

            # Send via SMTP
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender_email, self.app_password)
                server.send_message(msg)

            logger.info(f"Email sent to {recipient}")
            return {"success": True, "error": None}

        except smtplib.SMTPAuthenticationError:
            error = "Gmail authentication failed. Check your App Password."
            logger.error(error)
            return {"success": False, "error": error}

        except smtplib.SMTPRecipientsRefused:
            error = f"Recipient refused: {recipient}"
            logger.error(error)
            return {"success": False, "error": error}

        except Exception as e:
            error = f"Failed to send email: {str(e)}"
            logger.error(error)
            return {"success": False, "error": error}
