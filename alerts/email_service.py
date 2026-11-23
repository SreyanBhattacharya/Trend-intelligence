import logging
import smtplib
from email.message import EmailMessage

import config

logger = logging.getLogger(__name__)


class EmailService:
    def __init__(self):
        self.smtp_server = config.env("SMTP_SERVER", "smtp.gmail.com")
        self.smtp_port = int(config.env("SMTP_PORT", "587"))
        self.smtp_username = config.env("SMTP_USERNAME")
        self.smtp_password = config.env("SMTP_PASSWORD")
        self.from_email = config.env("FROM_EMAIL", self.smtp_username)
        self.to_email = config.env("ALERT_TO_EMAIL")

    def send_alert(self, subject: str, body: str) -> bool:
        if not all([self.smtp_username, self.smtp_password, self.to_email]):
            logger.debug("Email credentials not fully configured. Email alert skipped.")
            return False
        try:
            msg = EmailMessage()
            msg.set_content(body)
            msg["Subject"] = subject
            msg["From"] = self.from_email
            msg["To"] = self.to_email
            with smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=20) as server:
                server.starttls()
                server.login(self.smtp_username, self.smtp_password)
                server.send_message(msg)
            logger.info("Email alert sent to %s: %s", self.to_email, subject)
            return True
        except Exception as e:
            logger.error("Failed to send email alert: %s", e)
            return False
