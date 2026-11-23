"""End-to-end pipeline against a real Postgres (set TEST_DATABASE_URL)."""
import datetime as dt

from sqlalchemy import text

from agents.data_collection_agent import DataCollectionAgent
from services import demo_source
from workflows.pipeline import run_pipeline


def _demo_posts_at_peak():
    """Demo posts shifted so an emerging topic is ~8h into its rise right now."""
    now = dt.datetime.now(dt.timezone.utc)
    for offset in range(12):
        fake = now + dt.timedelta(hours=offset)
        peak = [e for e in demo_source.emerging_topics_at(fake) if e["age"] == 8]
        if peak:
            posts = demo_source.generate_posts(now=fake)
            for p in posts:
                p["posted_at"] -= offset * 3600
            return posts, peak[0]["topic"]
    raise AssertionError("demo cycle has no peak")


def test_full_pipeline_detects_scores_and_alerts_once(db, capsys):
    posts, topic = _demo_posts_at_peak()
    assert DataCollectionAgent()._store("demo", posts) == len(posts)

    first = run_pipeline()
    assert first["posts_processed"] == len(posts)
    assert first["trends_detected"] >= 1 and first["alerts_sent"] >= 1
    assert "ALERT: NEW VIRAL TREND DETECTED" in capsys.readouterr().out

    with db.connect() as conn:
        trend = conn.execute(text("""
            SELECT t.id, t.platforms, p.trend_score, p.virality_probability
            FROM trends t JOIN latest_trend_predictions p ON p.trend_id = t.id
            WHERE t.trend_key = :k"""), {"k": topic}).mappings().one()
        assert trend["virality_probability"] >= 70 and trend["trend_score"] >= 80
        assert set(trend["platforms"]) == {"reddit", "twitter", "youtube"}
        assert conn.execute(text("SELECT COUNT(*) FROM engagement_metrics WHERE trend_id = :i"),
                            {"i": trend["id"]}).scalar() == 27
        assert conn.execute(text("SELECT COUNT(*) FROM content_ideas WHERE trend_id = :i"),
                            {"i": trend["id"]}).scalar() == 1

    # Re-running on the same data must not duplicate trends, ideas or alerts.
    DataCollectionAgent()._store("demo", posts)
    second = run_pipeline()
    assert second["posts_processed"] == 0 and second["alerts_sent"] == 0 and second["ideas_generated"] == 0
    with db.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM trends WHERE trend_key = :k"), {"k": topic}).scalar() == 1
        assert conn.execute(text("SELECT COUNT(*) FROM alerts")).scalar() == first["alerts_sent"]


def test_pipeline_with_no_data_is_a_no_op(db):
    assert run_pipeline() == {"posts_processed": 0, "trends_detected": 0, "trends_scored": 0,
                              "ideas_generated": 0, "alerts_sent": 0}


def test_init_db_is_idempotent(db):
    from database.db_connection import init_db

    init_db()
    init_db()
