import logging
from typing import Dict, List

from sqlalchemy import text

import config
from alerts.discord_service import DiscordService
from alerts.email_service import EmailService
from alerts.slack_service import SlackService
from database.db_connection import get_engine

logger = logging.getLogger(__name__)

DUE_ALERTS = text("""
    SELECT t.id, t.trend_name, t.platform, t.platforms, t.description,
           p.trend_score, p.virality_probability, p.trend_momentum, p.estimated_lifespan_days
    FROM trends t
    JOIN latest_trend_predictions p ON t.id = p.trend_id
    WHERE t.is_active = TRUE
      AND p.trend_score >= :score_thresh
      AND p.virality_probability >= :viral_thresh
      AND NOT EXISTS (
          SELECT 1 FROM alerts a
          WHERE a.trend_id = t.id AND a.alerted_at > now() - make_interval(hours => :cooldown)
      )
    ORDER BY p.virality_probability DESC, p.trend_score DESC
""")

LATEST_IDEA = text("""
    SELECT suggested_format, suggested_caption, suggested_hashtags, hook
    FROM content_ideas WHERE trend_id = :trend_id ORDER BY generated_at DESC LIMIT 1
""")

INSERT_ALERT = text("""
    INSERT INTO alerts (trend_id, alerted_at, channels_sent, alert_type)
    VALUES (:trend_id, CURRENT_TIMESTAMP, :channels, 'high_virality')
""")


class NotificationAgent:
    """Sends alerts (Slack, Discord, email, console fallback) for trends above both thresholds."""

    def __init__(self):
        self.email_service = EmailService()
        self.slack_service = SlackService()
        self.discord_service = DiscordService()
        self._load_config()

    def _load_config(self):
        t = config.section("thresholds")
        self.trend_score_threshold = config.as_percent(t.get("trend_score_alert_threshold", 80))
        # Stored predictions are percentages (0-100); config may say 0.7 or 70.
        self.virality_threshold = config.as_percent(t.get("virality_probability_alert_threshold", 70))
        self.cooldown_hours = int(t.get("alert_cooldown_hours", 24))

    def check_and_notify(self) -> List[Dict]:
        engine = get_engine()
        if engine is None:
            return []
        logger.info("Starting notification agent run.")
        sent = []
        try:
            with engine.connect() as conn:
                due = conn.execute(DUE_ALERTS, {
                    "score_thresh": self.trend_score_threshold,
                    "viral_thresh": self.virality_threshold,
                    "cooldown": self.cooldown_hours,
                }).mappings().fetchall()
                ideas = {t["id"]: conn.execute(LATEST_IDEA, {"trend_id": t["id"]}).mappings().first() for t in due}
        except Exception as e:
            logger.error("Error loading alerts: %s", e)
            return []

        if not due:
            logger.info("No trends triggered alert thresholds.")
            return []

        for trend in due:
            message = self._format_alert(trend, ideas.get(trend["id"]))
            channels = self._dispatch(trend, message)
            try:
                # One transaction per alert so a failure never causes re-sends of the others.
                with engine.begin() as conn:
                    conn.execute(INSERT_ALERT, {"trend_id": trend["id"], "channels": channels})
                sent.append({"trend_id": trend["id"], "trend_name": trend["trend_name"], "channels": channels})
                logger.info("Alert sent for trend '%s' via %s", trend["trend_name"], channels)
            except Exception as e:
                logger.error("Failed to record alert for '%s': %s", trend["trend_name"], e)
        return sent

    def _dispatch(self, trend, message: str) -> List[str]:
        channels = []
        if self.slack_service.send_alert(f"🚀 Trending Alert!\n\n{message}"):
            channels.append("slack")
        if self.discord_service.send_alert(f"🚀 **Trending Alert!**\n\n{message}"):
            channels.append("discord")
        if self.email_service.send_alert(f"Trending Alert: {trend['trend_name']}", message):
            channels.append("email")
        if not channels:
            bar = "=" * 50
            print(f"\n{bar}\nALERT: NEW VIRAL TREND DETECTED\n{bar}\n{message}{bar}\n", flush=True)
            channels.append("console")
        return channels

    @staticmethod
    def _format_alert(trend, idea) -> str:
        platforms = ", ".join(trend.get("platforms") or []) or trend.get("platform") or "aggregated"
        msg = f"Trend: \"{trend['trend_name']}\"\n"
        msg += f"Platforms: {platforms}\n"
        msg += f"Trend Score: {trend['trend_score']:.1f}\n"
        msg += f"Virality Probability: {trend['virality_probability']:.1f}%\n"
        if trend.get("estimated_lifespan_days"):
            msg += f"Estimated Lifespan: ~{trend['estimated_lifespan_days']} day(s)\n"
        if trend.get("description"):
            msg += f"Signal: {trend['description']}\n"
        if idea:
            msg += "\nSuggested Content Idea:\n"
            msg += f"Format: {idea['suggested_format']}\n"
            msg += f"Hook: \"{idea['hook']}\"\n"
            msg += f"Caption: \"{idea['suggested_caption']}\"\n"
            tags = " ".join(idea["suggested_hashtags"] or [])
            msg += f"Hashtags: {tags}\n"
        return msg
