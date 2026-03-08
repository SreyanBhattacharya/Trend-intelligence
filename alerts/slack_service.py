import os
import logging
import requests

logger = logging.getLogger(__name__)

class SlackService:
    def __init__(self):
        self.webhook_url = os.getenv("SLACK_WEBHOOK_URL")

    def send_alert(self, message: str) -> bool:
        if not self.webhook_url:
            logger.warning("SLACK_WEBHOOK_URL not configured. Slack alert skipped.")
            return False
            
        try:
            payload = {"text": message}
            response = requests.post(self.webhook_url, json=payload, timeout=10)
            response.raise_for_status()
            logger.info("Slack alert sent successfully.")
            return True
        except Exception as e:
            logger.error(f"Failed to send Slack alert: {e}")
            return False
