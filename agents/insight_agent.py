import os
import logging
from sqlalchemy import text
from database.db_connection import engine
import json

logger = logging.getLogger(__name__)

class InsightAgent:
    """Agent that uses LLM APIs to generate content ideas for high-scoring trends."""
    
    def __init__(self):
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        if getattr(self, "openai_api_key", None):
            try:
                import openai
                openai.api_key = self.openai_api_key
                self.client = openai.OpenAI(api_key=self.openai_api_key)
                self.has_llm = True
                logger.info("Insight agent initialized with OpenAI API.")
            except ImportError:
                self.has_llm = False
                logger.warning("OpenAI library not installed. Insight Agent will run in mock mode.")
        else:
            self.has_llm = False
            logger.warning("No OPENAI_API_KEY found. Insight Agent will run in mock mode.")

    def generate_insights(self):
        if not engine:
            return
            
        logger.info("Starting insight generation agent run.")
        
        # Find active trends with high virality probability that don't have ideas generated recently
        query = text("""
            SELECT t.id, t.trend_name, t.description, p.virality_probability
            FROM trends t
            JOIN trend_predictions p ON t.id = p.trend_id
            WHERE t.is_active = TRUE AND p.virality_probability > 70.0
            AND NOT EXISTS (
                SELECT 1 FROM content_ideas c 
                WHERE c.trend_id = t.id 
                AND c.generated_at > NOW() - INTERVAL '24 HOURS'
            )
        """)
        
        insert_idea_query = text("""
            INSERT INTO content_ideas (trend_id, suggested_format, suggested_caption, suggested_hashtags, hook)
            VALUES (:trend_id, :fmt, :caption, :tags, :hook)
        """)
        
        try:
            with engine.connect() as conn:
                trends = conn.execute(query).mappings().fetchall()
                if not trends:
                    logger.info("No high-potential trends requiring new insights.")
                    return
                    
                with conn.begin():
                    for trend in trends:
                        idea = self._call_llm(trend['trend_name'], trend['description'])
                        
                        conn.execute(insert_idea_query, {
                            "trend_id": trend['id'],
                            "fmt": idea.get('format', 'Reel/TikTok'),
                            "caption": idea.get('caption', 'Check this out!'),
                            "tags": idea.get('hashtags', ['#trend']),
                            "hook": idea.get('hook', 'You won\'t believe this!')
                        })
                        logger.info(f"Generated insight for trend: {trend['trend_name']}")
                        
        except Exception as e:
            logger.error(f"Error in insight agent: {e}")

    def _call_llm(self, trend_name: str, description: str) -> dict:
        """Call OpenAI or return mocked output."""
        if not self.has_llm:
            return {
                "format": "TikTok/Reels",
                "caption": f"POV: You just discovered the {trend_name} trend! {description}",
                "hashtags": [f"#{trend_name.replace(' ', '')}", "#AITrend", "#Viral"],
                "hook": f"Stop scrolling if you don't know about {trend_name}."
            }
            
        try:
            prompt = f"""
            You are a social media trend analyst. I have detected a highly viral trend:
            Trend Name: {trend_name}
            Context: {description}
            
            Generate a JSON object with a content idea containing:
            1. "format": The best medium (e.g. TikTok, Twitter thread, Instagram Reel).
            2. "hook": A catchy opening line to grab attention in the first 3 seconds.
            3. "caption": A short, engaging caption.
            4. "hashtags": Array of 3-5 relevant hashtags.
            
            Return ONLY valid JSON.
            """
            
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
            )
            
            result = response.choices[0].message.content
            # Clean up potential markdown formatting
            result = result.replace('```json', '').replace('```', '').strip()
            
            return json.loads(result)
        except Exception as e:
            logger.error(f"LLM generation failed: {e}. Falling back to mock.")
            return {
                "format": "Tweet",
                "caption": f"Everyone is talking about {trend_name}. Thoughts?",
                "hashtags": [f"#{trend_name.replace(' ', '')}", "#Trending"],
                "hook": f"Have you heard of {trend_name}?"
            }
