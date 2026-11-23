import datetime as dt
import logging
import math
from collections import defaultdict
from typing import Dict, Iterable, Tuple

from sqlalchemy import text

import config
from data_processing.cleaning_pipeline import clean_text, normalize_term
from data_processing.keyword_extraction import MAX_LEN, MIN_LEN, extract_keywords
from database.db_connection import get_engine

logger = logging.getLogger(__name__)

BATCH_SIZE = 500
MAX_BATCHES_PER_RUN = 20

SELECT_UNPROCESSED = text("""
    SELECT id, title, body, hashtags, platform, likes, comments, views, shares, posted_at, collected_at
    FROM posts WHERE processed = FALSE ORDER BY id LIMIT :limit
    FOR UPDATE SKIP LOCKED
""")

UPDATE_POST = text("""
    UPDATE posts SET processed = TRUE, engagement_score = :score, keywords = :keywords WHERE id = :id
""")

UPSERT_MENTIONS = text("""
    INSERT INTO keyword_mentions (word, bucket, platform, mentions, engagement)
    VALUES (:word, :bucket, :platform, :mentions, :engagement)
    ON CONFLICT (word, bucket, platform) DO UPDATE SET
        mentions = keyword_mentions.mentions + EXCLUDED.mentions,
        engagement = keyword_mentions.engagement + EXCLUDED.engagement
""")

UPSERT_KEYWORD = text("""
    INSERT INTO keywords (word, frequency, first_seen, last_seen)
    VALUES (:word, :count, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    ON CONFLICT (word) DO UPDATE SET
        frequency = keywords.frequency + EXCLUDED.frequency,
        last_seen = CURRENT_TIMESTAMP
""")


def raw_engagement(post) -> float:
    return float((post.get("likes") or 0) + 2 * (post.get("comments") or 0) + 3 * (post.get("shares") or 0))


def engagement_score(post) -> float:
    """0-100 score. Uses engagement rate when views are known, else absolute engagement."""
    raw = raw_engagement(post)
    views = post.get("views") or 0
    if views > 0:
        return round(min(100.0, max(0.0, math.log1p(raw / views * 10000) * 10)), 2)
    return round(min(100.0, max(0.0, math.log1p(raw) * 10)), 2)


def mention_bucket(post, old_after_hours: int = 48) -> dt.datetime:
    """Hour the mention is counted in: when it was posted, unless the post was
    already older than ``old_after_hours`` when we first saw it (e.g. a days-old
    video on YouTube's trending chart), in which case it counts when observed.
    The cut-off must sit outside the detection window, otherwise posts crossing it
    would jump into the current hour and fake a spike."""
    collected = post.get("collected_at") or dt.datetime.now(dt.timezone.utc)
    posted = post.get("posted_at") or collected
    when = posted if posted >= collected - dt.timedelta(hours=old_after_hours) else collected
    return when.astimezone(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)


def post_terms(post) -> set:
    text_ = clean_text(f"{post.get('title') or ''} {post.get('body') or ''}")
    terms = set(extract_keywords(text_))
    terms.update(normalize_term(h) for h in (post.get("hashtags") or []))
    if post.get("platform") == "google_trends" and post.get("title"):
        terms.add(normalize_term(post["title"]))  # the search query itself is the trend
    return {t for t in terms if MIN_LEN <= len(t) <= MAX_LEN}


class DataProcessingAgent:
    """Cleans posts, extracts keywords and builds the hourly keyword time series."""

    def __init__(self):
        d = config.section("detection")
        span = int(d.get("baseline_window_hours", 24)) + int(d.get("current_window_hours", 3))
        self.old_after_hours = max(int(d.get("count_old_posts_when_seen_after_hours", 48)), span + 1)

    def process_unprocessed_posts(self) -> int:
        engine = get_engine()
        if engine is None:
            return 0
        logger.info("Starting data processing agent run.")
        total = 0
        try:
            for _ in range(MAX_BATCHES_PER_RUN):
                n = self._process_batch(engine)
                total += n
                if n < BATCH_SIZE:
                    break
        except Exception as e:
            logger.error("Error in data processing: %s", e)
        logger.info("Data processing complete. Processed %d posts.", total)
        return total

    def _process_batch(self, engine) -> int:
        with engine.begin() as conn:
            posts = conn.execute(SELECT_UNPROCESSED, {"limit": BATCH_SIZE}).mappings().fetchall()
            if not posts:
                return 0

            mentions: Dict[Tuple[str, dt.datetime, str], list] = defaultdict(lambda: [0, 0.0])
            keyword_counts: Dict[str, int] = defaultdict(int)
            updates = []
            for post in posts:
                terms = post_terms(post)
                bucket = mention_bucket(post, self.old_after_hours)
                eng = raw_engagement(post)
                for term in terms:
                    key = (term, bucket, post["platform"])
                    mentions[key][0] += 1
                    mentions[key][1] += eng
                    keyword_counts[term] += 1
                updates.append({"id": post["id"], "score": engagement_score(post), "keywords": sorted(terms)})

            if mentions:
                conn.execute(UPSERT_MENTIONS, list(self._mention_rows(mentions)))
                conn.execute(UPSERT_KEYWORD, [{"word": w, "count": c} for w, c in keyword_counts.items()])
            conn.execute(UPDATE_POST, updates)
            return len(posts)

    @staticmethod
    def _mention_rows(mentions) -> Iterable[Dict]:
        for (word, bucket, platform), (count, eng) in mentions.items():
            yield {"word": word, "bucket": bucket, "platform": platform, "mentions": count, "engagement": eng}

    # Compatibility helper used by older tests/callers.
    def _calculate_engagement_score(self, post) -> float:
        return engagement_score(post)
