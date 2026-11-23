import logging

import requests

import config

logger = logging.getLogger(__name__)


class SlackService:
    def __init__(self):
        self.webhook_url = config.env("SLACK_WEBHOOK_URL")

    def send_alert(self, message: str) -> bool:
        if not self.webhook_url:
            logger.debug("SLACK_WEBHOOK_URL not configured. Slack alert skipped.")
            return False
        try:
            response = requests.post(self.webhook_url, json={"text": message}, timeout=10)
            response.raise_for_status()
            logger.info("Slack alert sent successfully.")
            return True
        except Exception as e:
            logger.error("Failed to send Slack alert: %s", e)
            return False
