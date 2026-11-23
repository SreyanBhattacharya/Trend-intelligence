import logging

import requests

import config

logger = logging.getLogger(__name__)


class DiscordService:
    def __init__(self):
        self.webhook_url = config.env("DISCORD_WEBHOOK_URL")

    def send_alert(self, message: str) -> bool:
        if not self.webhook_url:
            logger.debug("DISCORD_WEBHOOK_URL not configured. Discord alert skipped.")
            return False
        try:
            # Discord rejects messages over 2000 characters.
            response = requests.post(self.webhook_url, json={"content": message[:1990]}, timeout=10)
            response.raise_for_status()
            logger.info("Discord alert sent successfully.")
            return True
        except Exception as e:
            logger.error("Failed to send Discord alert: %s", e)
            return False
