import datetime as dt
import logging
from collections import defaultdict
from typing import Dict, List

from sqlalchemy import text

import config
from ai_models.trend_model import DEFAULT_IGNORE_TERMS, cluster_topics, detect_spikes, merge_contained
from database.db_connection import get_engine

logger = logging.getLogger(__name__)

# Hourly counts for every term that is busy enough in the current window to matter.
SERIES_QUERY = text("""
    WITH win AS (
        SELECT date_trunc('hour', now()) - make_interval(hours => :span - 1) AS start_bucket,
               date_trunc('hour', now()) - make_interval(hours => :current - 1) AS current_start
    ),
    candidates AS (
        SELECT k.word
        FROM keyword_mentions k, win
        WHERE k.bucket >= win.current_start
        GROUP BY k.word
        HAVING SUM(k.mentions) >= :min_mentions
    )
    SELECT k.word, k.bucket, k.platform, k.mentions, k.engagement
    FROM keyword_mentions k
    JOIN candidates c ON c.word = k.word, win
    WHERE k.bucket >= win.start_bucket
""")

UPSERT_TREND = text("""
    INSERT INTO trends (trend_key, trend_name, description, platform, platforms, source, z_score,
                        related_post_ids, is_active, last_seen_at)
    VALUES (:key, :name, :desc, :platform, :platforms, :source, :z, :post_ids, TRUE, CURRENT_TIMESTAMP)
    ON CONFLICT (trend_key) DO UPDATE SET
        description = EXCLUDED.description,
        platform = EXCLUDED.platform,
        platforms = EXCLUDED.platforms,
        z_score = EXCLUDED.z_score,
        related_post_ids = EXCLUDED.related_post_ids,
        is_active = TRUE,
        last_seen_at = CURRENT_TIMESTAMP
    RETURNING id, (xmax = 0) AS inserted
""")

RELATED_POSTS = text("""
    SELECT id FROM posts
    WHERE keywords @> ARRAY[CAST(:word AS TEXT)]
      AND COALESCE(posted_at, collected_at) >= now() - make_interval(hours => :span)
    ORDER BY engagement_score DESC NULLS LAST
    LIMIT 200
""")

POSTS_WITH_TERMS = text("""
    SELECT id, keywords FROM posts
    WHERE keywords && CAST(:terms AS TEXT[])
      AND COALESCE(posted_at, collected_at) >= now() - make_interval(hours => :span)
""")

GOOGLE_TRENDS_QUERY = text("""
    SELECT id, title FROM posts
    WHERE platform = 'google_trends' AND collected_at >= now() - make_interval(hours => :current)
""")

RECENT_POSTS = text("""
    SELECT id, title, body, platform FROM posts
    WHERE processed = TRUE AND COALESCE(posted_at, collected_at) >= now() - make_interval(hours => :span)
    LIMIT 2000
""")

DEACTIVATE = text("""
    UPDATE trends SET is_active = FALSE
    WHERE is_active = TRUE AND last_seen_at < now() - make_interval(hours => :hours)
""")


class TrendDetectionAgent:
    """Finds emerging trends: keyword spikes vs. their own baseline, Google
    Trends searches, and (optionally) BERTopic topic clusters."""

    def __init__(self):
        d = config.section("detection")
        self.current_hours = int(d.get("current_window_hours", 3))
        self.baseline_hours = int(d.get("baseline_window_hours", 24))
        self.min_mentions = int(d.get("min_mentions", 5))
        self.z_threshold = float(d.get("z_score_threshold", 2.5))
        self.growth_threshold = float(d.get("growth_ratio_threshold", 3.0))
        self.max_trends = int(d.get("max_trends_per_run", 25))
        self.inactive_after = int(d.get("trend_inactive_after_hours", 48))
        self.use_clustering = bool(d.get("topic_clustering", False))
        self.ignore_terms = set(DEFAULT_IGNORE_TERMS) | {t.lower() for t in d.get("ignore_terms", [])}

    @property
    def span(self) -> int:
        return self.baseline_hours + self.current_hours

    def load_term_series(self, conn) -> Dict[str, Dict]:
        rows = conn.execute(SERIES_QUERY, {"span": self.span, "current": self.current_hours,
                                           "min_mentions": self.min_mentions}).mappings().fetchall()
        now_bucket = dt.datetime.now(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)
        series: Dict[str, Dict] = defaultdict(lambda: {"hourly": [0] * self.span, "platforms": set(), "engagement": 0.0})
        for r in rows:
            idx = self.span - 1 - int((now_bucket - r["bucket"]).total_seconds() // 3600)
            if 0 <= idx < self.span:
                s = series[r["word"]]
                s["hourly"][idx] += r["mentions"]
                if idx >= self.span - self.current_hours:
                    s["platforms"].add(r["platform"])
                    s["engagement"] += r["engagement"]
        return dict(series)

    def detect_trends(self) -> List[Dict]:
        engine = get_engine()
        if engine is None:
            return []
        logger.info("Starting trend detection agent run.")
        detected: List[Dict] = []
        try:
            with engine.begin() as conn:
                spikes = detect_spikes(
                    self.load_term_series(conn), current_hours=self.current_hours,
                    min_mentions=self.min_mentions, z_threshold=self.z_threshold,
                    growth_threshold=self.growth_threshold, max_results=self.max_trends * 3,
                    ignore_terms=self.ignore_terms)
                if spikes:
                    rows = conn.execute(POSTS_WITH_TERMS, {"terms": [s["word"] for s in spikes], "span": self.span})
                    spikes = merge_contained(spikes, {r[0]: set(r[1] or []) for r in rows})[: self.max_trends]

                for s in spikes:
                    social = [p for p in s["platforms"] if p != "google_trends"]
                    desc = (f"{s['frequency']} mentions in the last {self.current_hours}h vs. a baseline of "
                            f"{s['baseline_mean']:.1f} per {self.current_hours}h "
                            f"(z={s['z_score']:.1f}, x{s['growth_ratio']:.1f}) across {', '.join(s['platforms'])}.")
                    detected.append(self._upsert(conn, key=s["word"], name=s["word"], desc=desc,
                                                 platforms=s["platforms"], source="keyword_spike",
                                                 z=s["z_score"], platform=social[0] if len(social) == 1 else "aggregated"))

                for row in conn.execute(GOOGLE_TRENDS_QUERY, {"current": self.current_hours}).mappings():
                    key = row["title"].strip().lower()
                    if key and not any(d["key"] == key for d in detected):
                        detected.append(self._upsert(conn, key=key, name=row["title"].strip(), source="google_trends",
                                                     desc="Trending search on Google Trends.", platforms=["google_trends"],
                                                     z=0.0, platform="google_trends"))

                if self.use_clustering:
                    posts = conn.execute(RECENT_POSTS, {"span": self.span}).mappings().fetchall()
                    for c in cluster_topics([dict(p) for p in posts]):
                        detected.append(self._upsert(conn, key=f"topic:{c['topic_name']}", name=c["topic_name"],
                                                     desc=f"Topic cluster of {c['size']} recent posts.",
                                                     platforms=[], source="topic_cluster", z=0.0,
                                                     platform="aggregated", post_ids=c["post_ids"][:200]))

                stale = conn.execute(DEACTIVATE, {"hours": self.inactive_after}).rowcount
                if stale:
                    logger.info("Marked %d stale trends inactive.", stale)

            new = [d for d in detected if d["inserted"]]
            logger.info("Trend detection complete: %d trends (%d new).", len(detected), len(new))
        except Exception as e:
            logger.error("Error in trend detection: %s", e)
        return detected

    def _upsert(self, conn, key, name, desc, platforms, source, z, platform, post_ids=None) -> Dict:
        key = key[:255]
        if post_ids is None:
            post_ids = [r[0] for r in conn.execute(RELATED_POSTS, {"word": key, "span": self.span})]
        row = conn.execute(UPSERT_TREND, {
            "key": key, "name": name[:255], "desc": desc, "platform": platform, "platforms": list(platforms),
            "source": source, "z": float(z), "post_ids": post_ids,
        }).mappings().one()
        if row["inserted"]:
            logger.info("Detected new trend: %s (ID: %s, %s)", name, row["id"], source)
        return {"id": row["id"], "key": key, "name": name, "source": source, "inserted": bool(row["inserted"])}
