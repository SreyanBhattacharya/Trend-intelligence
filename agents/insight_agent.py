import json
import logging
import os
import re
from typing import Dict, List

from sqlalchemy import text

import config
from database.db_connection import get_engine

logger = logging.getLogger(__name__)

CANDIDATES = text("""
    SELECT t.id, t.trend_name, t.description, t.platforms, t.related_post_ids,
           p.virality_probability, p.trend_score
    FROM trends t
    JOIN latest_trend_predictions p ON t.id = p.trend_id
    WHERE t.is_active = TRUE AND p.virality_probability >= :threshold
      AND NOT EXISTS (
          SELECT 1 FROM content_ideas c
          WHERE c.trend_id = t.id AND c.generated_at > now() - INTERVAL '24 hours'
      )
    ORDER BY p.virality_probability DESC
    LIMIT :limit
""")

SAMPLE_POSTS = text("""
    SELECT COALESCE(NULLIF(title, ''), LEFT(body, 200)) AS text FROM posts
    WHERE id = ANY(:ids) ORDER BY engagement_score DESC NULLS LAST LIMIT 5
""")

INSERT_IDEA = text("""
    INSERT INTO content_ideas (trend_id, suggested_format, suggested_caption, suggested_hashtags, hook, generator)
    VALUES (:trend_id, :fmt, :caption, :tags, :hook, :generator)
""")

PLATFORM_NAMES = {"youtube": "YouTube", "twitter": "X/Twitter", "reddit": "Reddit", "google_trends": "Google"}

FORMAT_BY_PLATFORM = {
    "youtube": "YouTube Short",
    "twitter": "X/Twitter thread",
    "reddit": "Carousel post (Instagram/LinkedIn)",
    "google_trends": "TikTok/Reels explainer",
}


def hashtag(term: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", term)
    return "#" + "".join(w if w.isupper() and len(w) <= 4 else w.capitalize() for w in words) if words else ""


class InsightAgent:
    """Generates content ideas (format, hook, caption, hashtags) for high-potential trends.

    Uses OpenAI when ``OPENAI_API_KEY`` is set (model from ``OPENAI_MODEL``,
    default gpt-4o-mini); otherwise a template generator so the pipeline still
    produces usable output.
    """

    def __init__(self):
        self.threshold = config.as_percent(config.section("thresholds").get("insight_virality_threshold", 60))
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.client = None
        api_key = config.env("OPENAI_API_KEY")
        if api_key:
            try:
                from openai import OpenAI

                self.client = OpenAI(api_key=api_key)
                logger.info("Insight agent using OpenAI model %s.", self.model)
            except Exception as e:
                logger.warning("OpenAI client unavailable (%s); using template generator.", e)
        else:
            logger.info("No OPENAI_API_KEY set; Insight Agent uses the template generator.")

    @property
    def has_llm(self) -> bool:
        return self.client is not None

    def generate_insights(self, limit: int = 20) -> List[Dict]:
        engine = get_engine()
        if engine is None:
            return []
        logger.info("Starting insight generation agent run.")
        created = []
        try:
            with engine.begin() as conn:
                trends = conn.execute(CANDIDATES, {"threshold": self.threshold, "limit": limit}).mappings().fetchall()
                if not trends:
                    logger.info("No high-potential trends requiring new insights.")
                    return []
                for trend in trends:
                    samples = [r[0] for r in conn.execute(SAMPLE_POSTS, {"ids": trend["related_post_ids"] or []}) if r[0]]
                    idea = self.create_idea(trend["trend_name"], trend["description"] or "",
                                            list(trend["platforms"] or []), samples)
                    conn.execute(INSERT_IDEA, {"trend_id": trend["id"], **idea})
                    created.append({"trend_id": trend["id"], **idea})
                    logger.info("Generated %s insight for trend: %s", idea["generator"], trend["trend_name"])
        except Exception as e:
            logger.error("Error in insight agent: %s", e)
        return created

    def create_idea(self, trend_name: str, description: str, platforms: List[str], samples: List[str]) -> Dict:
        idea = None
        if self.client is not None:
            idea = self._call_llm(trend_name, description, platforms, samples)
        generator = self.model if idea else "template"
        idea = idea or self._template(trend_name, platforms)
        tags = [t if t.startswith("#") else f"#{t}" for t in (idea.get("hashtags") or [])][:5]
        return {
            "fmt": str(idea.get("format") or "TikTok/Reels")[:100],
            "caption": str(idea.get("caption") or ""),
            "tags": tags or [hashtag(trend_name)],
            "hook": str(idea.get("hook") or ""),
            "generator": generator,
        }

    @staticmethod
    def _template(trend_name: str, platforms: List[str]) -> Dict:
        lead = next((p for p in platforms if p in FORMAT_BY_PLATFORM), "google_trends")
        names = [PLATFORM_NAMES.get(p, p.title()) for p in platforms]
        where = (", ".join(names[:-1]) + " and " + names[-1]) if len(names) > 1 else (names[0] if names else "social media")
        return {
            "format": FORMAT_BY_PLATFORM[lead],
            "hook": f"Stop scrolling if you haven't seen {trend_name} yet.",
            "caption": f"Everyone on {where} is suddenly talking about {trend_name}. Here's what it is, "
                       f"why people care, and how to jump in before it peaks.",
            "hashtags": [hashtag(trend_name), "#Trending", "#" + PLATFORM_NAMES.get(lead, lead).replace("/", "")],
        }

    def _call_llm(self, trend_name: str, description: str, platforms: List[str], samples: List[str]):
        examples = "\n".join(f"- {s}" for s in samples) or "- (none)"
        prompt = (
            "You are a social media strategist. A trend is gaining momentum.\n"
            f"Trend: {trend_name}\nSignal: {description}\nPlatforms: {', '.join(platforms) or 'unknown'}\n"
            f"Example posts:\n{examples}\n\n"
            "Return a JSON object with keys: format (best medium, e.g. 'TikTok', 'X thread', 'Instagram Reel'), "
            "hook (opening line that grabs attention in 3 seconds), caption (short, engaging), "
            "hashtags (array of 3-5 hashtags)."
        )
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                response_format={"type": "json_object"},
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            logger.error("LLM generation failed for '%s': %s. Using template.", trend_name, e)
            return None
