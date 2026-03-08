import logging
from sqlalchemy import text
from database.db_connection import engine
from ai_models.trend_model import detect_spikes, cluster_topics

logger = logging.getLogger(__name__)

class TrendDetectionAgent:
    """Agent responsible for identifying emerging trends from processed data and keywords."""
    
    def detect_trends(self):
        if not engine:
            return
            
        logger.info("Starting trend detection agent run.")
        
        # 1. Look for keyword frequency spikes in the last X hours
        # In a real app we'd compare windows. Here we just query top frequent keywords recently.
        top_keywords_query = text("""
            SELECT word, frequency 
            FROM keywords 
            WHERE last_seen >= NOW() - INTERVAL '24 HOURS'
            ORDER BY frequency DESC 
            LIMIT 50
        """)
        
        # 2. Get recent posts for clustering
        recent_posts_query = text("""
            SELECT id, title, body, platform 
            FROM posts 
            WHERE processed = TRUE 
            AND posted_at >= EXTRACT(EPOCH FROM (NOW() - INTERVAL '48 HOURS'))
            LIMIT 1000
        """)
        
        insert_trend_query = text("""
            INSERT INTO trends (trend_name, description, platform)
            VALUES (:name, :desc, :platform)
            RETURNING id
        """)
        
        try:
            with engine.connect() as conn:
                kw_results = conn.execute(top_keywords_query).mappings().fetchall()
                post_results = conn.execute(recent_posts_query).mappings().fetchall()
                
                # Use the ML model to detect spikes (mocked/simplified logic in model file)
                spikes = detect_spikes(kw_results)
                
                # Use BERTopic to cluster topics
                clusters = cluster_topics(post_results)
                
                # Merging / Defining trends and inserting to DB
                # For simplicity, we just iterate through identified spikes and clusters
                with conn.begin():
                    for spike in spikes:
                        trend_id = conn.execute(insert_trend_query, {
                            "name": spike['word'],
                            "desc": f"Spike detected in keyword usage. Frequency: {spike['frequency']}",
                            "platform": "aggregated"
                        }).scalar()
                        
                        logger.info(f"Detected new trend: {spike['word']} (ID: {trend_id})")
                        
                    for cluster in clusters:
                        # Ensure we don't duplicate trends too heavily
                        if cluster['topic_name'] != "Outlier":
                            trend_id = conn.execute(insert_trend_query, {
                                "name": cluster['topic_name'],
                                "desc": f"Topic cluster detected from recent posts. Size: {cluster['size']}",
                                "platform": "aggregated"
                            }).scalar()
                            logger.info(f"Detected new topic trend: {cluster['topic_name']} (ID: {trend_id})")
                            
                logger.info("Trend detection complete.")
        except Exception as e:
            logger.error(f"Error in trend detection: {e}")
