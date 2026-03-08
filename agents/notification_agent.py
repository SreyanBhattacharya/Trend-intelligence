import logging
import yaml
from sqlalchemy import text
from database.db_connection import engine
from alerts.email_service import EmailService
from alerts.slack_service import SlackService

logger = logging.getLogger(__name__)

class NotificationAgent:
    """Agent that checks threshold limits and sends alerts for high-value trends."""
    
    def __init__(self):
        self.email_service = EmailService()
        self.slack_service = SlackService()
        self._load_config()

    def _load_config(self):
        # Default thresholds
        self.trend_score_threshold = 80.0
        self.virality_threshold = 70.0
        
        try:
            with open("config/config.yaml", "r") as f:
                config = yaml.safe_load(f)
                thresholds = config.get("platform_settings", {}).get("thresholds", {})
                self.trend_score_threshold = float(thresholds.get("trend_score_alert_threshold", 80.0))
                self.virality_threshold = float(thresholds.get("virality_probability_alert_threshold", 70.0))
        except Exception as e:
            logger.warning(f"Failed to load config.yaml, using default thresholds: {e}")

    def check_and_notify(self):
        if not engine:
            return
            
        logger.info("Starting notification agent run.")
        
        # Check for trends that meet threshold but haven't been alerted for recently
        query = text("""
            SELECT t.id, t.trend_name, t.platform, p.trend_score, p.virality_probability
            FROM trends t
            JOIN trend_predictions p ON t.id = p.trend_id
            WHERE t.is_active = TRUE 
            AND p.trend_score >= :score_thresh 
            AND p.virality_probability >= :viral_thresh
            AND NOT EXISTS (
                SELECT 1 FROM alerts a 
                WHERE a.trend_id = t.id 
                AND a.alerted_at > NOW() - INTERVAL '24 HOURS'
            )
        """)
        
        # Also grab an idea if we generated one
        idea_query = text("""
            SELECT suggested_format, suggested_caption, suggested_hashtags, hook 
            FROM content_ideas 
            WHERE trend_id = :trend_id 
            ORDER BY generated_at DESC LIMIT 1
        """)
        
        insert_alert_query = text("""
            INSERT INTO alerts (trend_id, alerted_at, channels_sent, alert_type)
            VALUES (:trend_id, CURRENT_TIMESTAMP, :channels, 'high_virality')
        """)
        
        try:
            with engine.connect() as conn:
                trends_to_alert = conn.execute(query, {
                    "score_thresh": self.trend_score_threshold,
                    "viral_thresh": self.virality_threshold
                }).mappings().fetchall()
                
                if not trends_to_alert:
                    logger.info("No trends triggered alert thresholds.")
                    return
                
                with conn.begin():
                    for trend in trends_to_alert:
                        # Get linked content idea
                        idea = conn.execute(idea_query, {"trend_id": trend['id']}).mappings().first()
                        
                        message = self._format_alert(trend, idea)
                        
                        # Try sending alerts
                        channels = []
                        if self.slack_service.send_alert(f"🚀 Trending Alert!\n\n{message}"):
                            channels.append('slack')
                        
                        if self.email_service.send_alert(f"Trending Alert: {trend['trend_name']}", message):
                            channels.append('email')
                            
                        # If no channel is configured, log it to console as fallback
                        if not channels:
                            print("\n\n" + "="*50)
                            print("ALERT: NEW VIRAL TREND DETECTED")
                            print("="*50)
                            print(message)
                            print("="*50 + "\n\n")
                            channels.append('console')
                        
                        # Record alert
                        conn.execute(insert_alert_query, {
                            "trend_id": trend['id'],
                            "channels": channels
                        })
                        
                        logger.info(f"Alert sent for trend: {trend['trend_name']} via {channels}")
                        
        except Exception as e:
            logger.error(f"Error in notification agent: {e}")

    def _format_alert(self, trend, idea):
        msg = f"Trend: \"{trend['trend_name']}\"\n"
        msg += f"Platform: {trend['platform']}\n"
        msg += f"Trend Score: {trend['trend_score']:.1f}\n"
        msg += f"Virality Probability: {trend['virality_probability']:.1f}%\n"
        
        if idea:
            msg += "\nSuggested Content Idea:\n"
            msg += f"Format: {idea['suggested_format']}\n"
            msg += f"Hook: \"{idea['hook']}\"\n"
            msg += f"Caption: \"{idea['suggested_caption']}\"\n"
            # Join hashtags properly if it's stored as array
            tags = " ".join(idea['suggested_hashtags']) if idea['suggested_hashtags'] else ""
            msg += f"Hashtags: {tags}\n"
            
        return msg
