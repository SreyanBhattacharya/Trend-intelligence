import logging
from sqlalchemy import text
from database.db_connection import engine
from data_processing.cleaning_pipeline import clean_text
from data_processing.keyword_extraction import extract_keywords

logger = logging.getLogger(__name__)

class DataProcessingAgent:
    """Agent responsible for cleaning, structuring, and feature extracting from raw posts."""
    
    def process_unprocessed_posts(self):
        if not engine:
            return
            
        logger.info("Starting data processing agent run.")
        
        select_query = text("""
            SELECT id, title, body, hashtags, platform, likes, comments, views, shares 
            FROM posts WHERE processed = FALSE LIMIT 500
        """)
        
        update_query = text("""
            UPDATE posts 
            SET processed = TRUE, engagement_score = :score 
            WHERE id = :id
        """)
        
        try:
            with engine.connect() as conn:
                result = conn.execute(select_query)
                posts = result.mappings().fetchall()
                
                if not posts:
                    logger.info("No new posts to process.")
                    return
                
                logger.info(f"Processing {len(posts)} posts.")
                
                # Start transaction for updates
                with conn.begin():
                    for post in posts:
                        full_text = f"{post['title']} {post['body']}"
                        cleaned_text = clean_text(full_text)
                        
                        # Extract keywords (spacy based)
                        combined_hashtags = list(post['hashtags']) if post['hashtags'] else []
                        keywords = extract_keywords(cleaned_text)
                        
                        all_terms = set(combined_hashtags + keywords)
                        
                        # Update keyword frequency in DB
                        self._update_keywords(conn, all_terms)
                        
                        # Calculate engagement score (basic formula)
                        score = self._calculate_engagement_score(post)
                        
                        # Update post
                        conn.execute(update_query, {"score": score, "id": post['id']})
                        
                logger.info("Data processing complete.")
        except Exception as e:
            logger.error(f"Error in data processing: {e}")

    def _calculate_engagement_score(self, post) -> float:
        # Weighting factors based on platform logic can go here.
        # General simple formula:
        likes = post.get('likes') or 0
        comments = post.get('comments') or 0
        shares = post.get('shares') or 0
        views = post.get('views') or 1  # Avoid division by zero
        
        if views <= 0:
             views = 1
             
        score = (likes * 1 + comments * 2 + shares * 3) / views
        # Normalize arbitrarily for our 0-100 logic later, maybe log scale
        import math
        normalized = min(100.0, max(0.0, math.log1p(score * 10000) * 10))
        return normalized

    def _update_keywords(self, conn, words: set):
        if not words:
            return
            
        insert_kw_query = text("""
            INSERT INTO keywords (word, frequency, last_seen)
            VALUES (:word, 1, CURRENT_TIMESTAMP)
            ON CONFLICT (word) DO UPDATE SET
                frequency = keywords.frequency + 1,
                last_seen = CURRENT_TIMESTAMP
        """)
        for w in words:
            if len(w) > 2 and len(w) < 50:
                conn.execute(insert_kw_query, {"word": w.lower()})
