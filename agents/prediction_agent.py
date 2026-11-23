import logging
from typing import Dict, List

from sqlalchemy import text

import config
from ai_models.prediction_model import predict_virality
from database.db_connection import get_engine

logger = logging.getLogger(__name__)

ACTIVE_TRENDS = text("""
    SELECT id, trend_key, trend_name, source, platforms, z_score, related_post_ids
    FROM trends WHERE is_active = TRUE
""")

# Zero-filled hourly series for a keyword trend (all platforms combined).
KEYWORD_SERIES = text("""
    WITH hours AS (
        SELECT generate_series(date_trunc('hour', now()) - make_interval(hours => :span - 1),
                               date_trunc('hour', now()), interval '1 hour') AS bucket
    )
    SELECT h.bucket AS timestamp,
           COALESCE(SUM(k.mentions), 0) AS mentions,
           COALESCE(SUM(k.engagement), 0) AS engagement,
           COUNT(DISTINCT k.platform) AS platforms
    FROM hours h
    LEFT JOIN keyword_mentions k ON k.bucket = h.bucket AND k.word = :word
    GROUP BY h.bucket ORDER BY h.bucket
""")

# Same, built from a fixed set of posts (topic clusters).
POST_SERIES = text("""
    WITH hours AS (
        SELECT generate_series(date_trunc('hour', now()) - make_interval(hours => :span - 1),
                               date_trunc('hour', now()), interval '1 hour') AS bucket
    )
    SELECT h.bucket AS timestamp,
           COUNT(p.id) AS mentions,
           COALESCE(SUM(p.likes + 2 * p.comments + 3 * p.shares), 0) AS engagement,
           COUNT(DISTINCT p.platform) AS platforms
    FROM hours h
    LEFT JOIN posts p ON date_trunc('hour', p.posted_at) = h.bucket AND p.id = ANY(:ids)
    GROUP BY h.bucket ORDER BY h.bucket
""")

UPSERT_METRIC = text("""
    INSERT INTO engagement_metrics (trend_id, timestamp, mentions, total_engagement, growth_rate)
    VALUES (:trend_id, :ts, :mentions, :engagement, :growth)
    ON CONFLICT (trend_id, timestamp) DO UPDATE SET
        mentions = EXCLUDED.mentions,
        total_engagement = EXCLUDED.total_engagement,
        growth_rate = EXCLUDED.growth_rate
""")

INSERT_PREDICTION = text("""
    INSERT INTO trend_predictions (trend_id, predicted_at, trend_score, virality_probability,
                                   trend_momentum, estimated_lifespan_days, model)
    VALUES (:trend_id, CURRENT_TIMESTAMP, :score, :prob, :mom, :life, :model)
""")


class PredictionAgent:
    """Records each active trend's hourly engagement series and scores it."""

    def __init__(self):
        d = config.section("detection")
        self.span = int(d.get("baseline_window_hours", 24)) + int(d.get("current_window_hours", 3))
        self.use_prophet = bool(d.get("use_prophet", True))

    def trend_series(self, conn, trend) -> List[Dict]:
        if trend["source"] == "topic_cluster":
            rows = conn.execute(POST_SERIES, {"span": self.span, "ids": trend["related_post_ids"] or []})
        else:
            rows = conn.execute(KEYWORD_SERIES, {"span": self.span, "word": trend["trend_key"]})
        return [dict(r) for r in rows.mappings()]

    def predict_trends(self) -> List[Dict]:
        engine = get_engine()
        if engine is None:
            return []
        logger.info("Starting prediction agent run.")
        results = []
        try:
            with engine.begin() as conn:
                trends = conn.execute(ACTIVE_TRENDS).mappings().fetchall()
                if not trends:
                    logger.info("No active trends to predict.")
                    return []

                for trend in trends:
                    series = self.trend_series(conn, trend)
                    self._record_metrics(conn, trend["id"], series)
                    if sum(p["mentions"] for p in series) == 0:
                        continue

                    recent_platforms = max([p["platforms"] for p in series[-3:]] + [len(trend["platforms"] or [])])
                    result = predict_virality(series, platform_count=recent_platforms,
                                              z_score=None, use_prophet=self.use_prophet)
                    conn.execute(INSERT_PREDICTION, {
                        "trend_id": trend["id"], "score": result["trend_score"],
                        "prob": result["virality_probability"], "mom": result["trend_momentum"],
                        "life": result["estimated_lifespan_days"], "model": result["model"],
                    })
                    results.append({"trend_id": trend["id"], "trend_name": trend["trend_name"], **result})
                    logger.info("Trend '%s' scored %.1f (virality %.1f%%, momentum %.3f)", trend["trend_name"],
                                result["trend_score"], result["virality_probability"], result["trend_momentum"])
            logger.info("Prediction run complete: %d trends scored.", len(results))
        except Exception as e:
            logger.error("Error in prediction agent: %s", e)
        return results

    @staticmethod
    def _record_metrics(conn, trend_id: int, series: List[Dict]) -> None:
        rows, prev = [], None
        for p in series:
            growth = 0.0 if prev is None else (p["mentions"] - prev) / (prev + 1.0)
            rows.append({"trend_id": trend_id, "ts": p["timestamp"], "mentions": int(p["mentions"]),
                         "engagement": int(p["engagement"]), "growth": round(growth, 4)})
            prev = p["mentions"]
        if rows:
            conn.execute(UPSERT_METRIC, rows)
