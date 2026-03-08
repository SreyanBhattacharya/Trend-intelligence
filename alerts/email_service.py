import os
import logging
import smtplib
from email.message import EmailMessage

logger = logging.getLogger(__name__)

class EmailService:
    def __init__(self):
        self.smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_username = os.getenv("SMTP_USERNAME")
        self.smtp_password = os.getenv("SMTP_PASSWORD")
        self.from_email = os.getenv("FROM_EMAIL", self.smtp_username)
        self.to_email = os.getenv("ALERT_TO_EMAIL")

    def send_alert(self, subject: str, body: str) -> bool:
        if not all([self.smtp_username, self.smtp_password, self.to_email]):
            logger.warning("Email credentials not fully configured. Email alert skipped.")
            return False
            
        try:
            msg = EmailMessage()
            msg.set_content(body)
            msg['Subject'] = subject
            msg['From'] = self.from_email
            msg['To'] = self.to_email

            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_username, self.smtp_password)
                server.send_message(msg)
                
            logger.info(f"Email alert sent to {self.to_email}: {subject}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email alert: {e}")
            return False
