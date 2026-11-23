"""Dashboard API + static front end.

    uvicorn api.server:app --port 8000      (or: python main.py web)

Read-only JSON endpoints over the platform's database, plus endpoints to
trigger a collection / pipeline run from the dashboard.
"""
import logging
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, HTTPException, Query  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, Response  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

import config  # noqa: E402
from database.db_connection import get_engine  # noqa: E402

logger = logging.getLogger(__name__)
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
PLATFORMS = ["reddit", "twitter", "youtube", "google_trends"]

app = FastAPI(title="Trend Intelligence API", version="1.0")


@app.exception_handler(OperationalError)
def database_unavailable(_request, exc):
    logger.error("Database unavailable: %s", exc)
    return JSONResponse(status_code=503, content={"detail": "Database unavailable. Is PostgreSQL running?"})


def _rows(sql: str, **params):
    with get_engine().connect() as conn:
        return [dict(r) for r in conn.execute(text(sql), params).mappings()]


def _one(sql: str, **params):
    rows = _rows(sql, **params)
    return rows[0] if rows else None


def _span() -> int:
    d = config.section("detection")
    return int(d.get("baseline_window_hours", 24)) + int(d.get("current_window_hours", 3))


# --- pages ---------------------------------------------------------------------

@app.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/health")
def health():
    try:
        _one("SELECT 1 AS ok")
        return {"status": "ok", "database": True}
    except Exception as e:
        return {"status": "degraded", "database": False, "error": str(e)}


# --- overview ------------------------------------------------------------------

@app.get("/api/overview")
def overview():
    t = config.section("thresholds")
    counts = _one("""
        SELECT (SELECT COUNT(*) FROM posts) AS posts_total,
               (SELECT COUNT(*) FROM posts WHERE collected_at > now() - interval '24 hours') AS posts_24h,
               (SELECT COUNT(*) FROM trends WHERE is_active) AS trends_active,
               (SELECT COUNT(*) FROM trends WHERE detected_at > now() - interval '24 hours') AS trends_new_24h,
               (SELECT COUNT(*) FROM alerts WHERE alerted_at > now() - interval '24 hours') AS alerts_24h,
               (SELECT COUNT(*) FROM alerts) AS alerts_total,
               (SELECT COUNT(*) FROM content_ideas) AS ideas_total,
               (SELECT COUNT(*) FROM keywords) AS keywords_tracked
    """)
    mix = _rows("""
        SELECT platform, COUNT(*) AS posts,
               COALESCE(SUM(likes + 2 * comments + 3 * shares), 0) AS engagement
        FROM posts WHERE COALESCE(posted_at, collected_at) > now() - interval '24 hours'
        GROUP BY platform ORDER BY posts DESC
    """)
    last_pipeline = _one("SELECT * FROM pipeline_runs WHERE task = 'pipeline' ORDER BY started_at DESC LIMIT 1")
    return {
        "now": datetime.now(timezone.utc),
        "demo_mode": config.demo_mode_enabled(),
        "sources": {
            "reddit": bool(config.env("REDDIT_CLIENT_ID")),
            "twitter": bool(config.env("TWITTER_BEARER_TOKEN")),
            "youtube": bool(config.env("YOUTUBE_API_KEY")),
            "google_trends": not config.demo_mode_enabled(),
            "demo": config.demo_mode_enabled(),
        },
        "channels": {
            "slack": bool(config.env("SLACK_WEBHOOK_URL")),
            "discord": bool(config.env("DISCORD_WEBHOOK_URL")),
            "email": bool(config.env("SMTP_USERNAME") and config.env("ALERT_TO_EMAIL")),
            "openai": bool(config.env("OPENAI_API_KEY")),
        },
        "thresholds": {
            "trend_score": config.as_percent(t.get("trend_score_alert_threshold", 80)),
            "virality": config.as_percent(t.get("virality_probability_alert_threshold", 70)),
            "insight": config.as_percent(t.get("insight_virality_threshold", 60)),
        },
        "counts": counts,
        "platform_mix": mix,
        "last_pipeline_run": last_pipeline,
        "run_in_progress": _runner.busy,
    }


# --- trends ----------------------------------------------------------------------

TREND_LIST_SQL = """
    SELECT t.id, t.trend_name, t.source, t.platforms, t.description, t.z_score, t.is_active,
           t.detected_at, t.last_seen_at,
           p.trend_score, p.virality_probability, p.trend_momentum, p.estimated_lifespan_days, p.model,
           p.predicted_at,
           (SELECT array_agg(m.mentions ORDER BY m.timestamp)
              FROM engagement_metrics m
             WHERE m.trend_id = t.id AND m.timestamp > now() - make_interval(hours => :span)) AS series,
           (SELECT json_object_agg(x.platform, x.m) FROM (
                SELECT k.platform, SUM(k.mentions) AS m FROM keyword_mentions k
                WHERE k.word = t.trend_key
                  AND k.bucket >= date_trunc('hour', now()) - make_interval(hours => :current - 1)
                GROUP BY k.platform) x) AS platform_split,
           (SELECT COUNT(*) FROM alerts a WHERE a.trend_id = t.id) AS alert_count,
           (SELECT MAX(a.alerted_at) FROM alerts a WHERE a.trend_id = t.id) AS last_alert_at,
           (SELECT row_to_json(c) FROM (
                SELECT suggested_format, hook, suggested_caption, suggested_hashtags, generator, generated_at
                FROM content_ideas WHERE trend_id = t.id ORDER BY generated_at DESC LIMIT 1) c) AS idea
    FROM trends t
    LEFT JOIN latest_trend_predictions p ON p.trend_id = t.id
    WHERE (:include_inactive OR t.is_active)
    ORDER BY t.is_active DESC, p.virality_probability DESC NULLS LAST, p.trend_score DESC NULLS LAST
    LIMIT :limit
"""


@app.get("/api/trends")
def trends(limit: int = Query(50, ge=1, le=500), include_inactive: bool = False):
    current = int(config.section("detection").get("current_window_hours", 3))
    return _rows(TREND_LIST_SQL, span=_span(), current=current, limit=limit, include_inactive=include_inactive)


@app.get("/api/trends/{trend_id}")
def trend_detail(trend_id: int):
    trend = _one("SELECT * FROM trends WHERE id = :id", id=trend_id)
    if not trend:
        raise HTTPException(404, "Trend not found")
    return {
        "trend": trend,
        "series": _rows("""
            SELECT timestamp, mentions, total_engagement, growth_rate FROM engagement_metrics
            WHERE trend_id = :id AND timestamp > now() - make_interval(hours => :span) ORDER BY timestamp
        """, id=trend_id, span=_span()),
        "predictions": _rows("""
            SELECT predicted_at, trend_score, virality_probability, trend_momentum, estimated_lifespan_days, model
            FROM trend_predictions WHERE trend_id = :id ORDER BY predicted_at DESC LIMIT 50
        """, id=trend_id),
        "posts": _rows("""
            SELECT id, platform, author, COALESCE(NULLIF(title, ''), LEFT(body, 280)) AS text, url,
                   posted_at, likes, comments, shares, views, engagement_score
            FROM posts WHERE id = ANY(:ids) ORDER BY engagement_score DESC NULLS LAST LIMIT 12
        """, ids=trend["related_post_ids"] or []),
        "ideas": _rows("SELECT * FROM content_ideas WHERE trend_id = :id ORDER BY generated_at DESC", id=trend_id),
        "alerts": _rows("SELECT * FROM alerts WHERE trend_id = :id ORDER BY alerted_at DESC", id=trend_id),
    }


# --- datasets -------------------------------------------------------------------

@app.get("/api/activity")
def activity(hours: int = Query(24, ge=1, le=168)):
    """Posts per hour per platform (zero-filled)."""
    rows = _rows("""
        WITH hours AS (
            SELECT generate_series(date_trunc('hour', now()) - make_interval(hours => :h - 1),
                                   date_trunc('hour', now()), interval '1 hour') AS bucket
        )
        SELECT h.bucket, p.platform, COUNT(p.id) AS posts
        FROM hours h
        LEFT JOIN posts p ON date_trunc('hour', COALESCE(p.posted_at, p.collected_at)) = h.bucket
        GROUP BY h.bucket, p.platform ORDER BY h.bucket
    """, h=hours)
    buckets = {}
    for r in rows:
        b = buckets.setdefault(r["bucket"], {"bucket": r["bucket"], "total": 0})
        if r["platform"]:
            b[r["platform"]] = r["posts"]
            b["total"] += r["posts"]
    return list(buckets.values())


@app.get("/api/posts")
def posts(platform: Optional[str] = None, q: Optional[str] = None,
          limit: int = Query(25, ge=1, le=200), offset: int = Query(0, ge=0)):
    where, params = ["TRUE"], {"limit": limit, "offset": offset}
    if platform:
        where.append("platform = :platform")
        params["platform"] = platform
    if q:
        where.append("(title ILIKE :q OR body ILIKE :q OR :kw = ANY(keywords))")
        params["q"] = f"%{q}%"
        params["kw"] = q.lower()
    clause = " AND ".join(where)
    total = _one(f"SELECT COUNT(*) AS n FROM posts WHERE {clause}", **params)["n"]
    rows = _rows(f"""
        SELECT id, platform, author, COALESCE(NULLIF(title, ''), LEFT(body, 280)) AS text, url,
               posted_at, collected_at, likes, comments, shares, views, engagement_score,
               keywords, processed
        FROM posts WHERE {clause}
        ORDER BY COALESCE(posted_at, collected_at) DESC LIMIT :limit OFFSET :offset
    """, **params)
    for r in rows:
        r["keywords"] = _specific_terms(r["keywords"] or [])
    return {"total": total, "items": rows}


def _specific_terms(terms, n: int = 3):
    """Most specific terms first, skipping ones contained in an already chosen phrase."""
    chosen = []
    for t in sorted(terms, key=lambda t: (-len(t.split()), t)):
        if " " not in t and any(t == c.replace(" ", "") for c in chosen):
            continue
        if not any(set(t.split()) <= set(c.split()) for c in chosen):
            chosen.append(t)
        if len(chosen) == n:
            break
    return chosen


@app.get("/api/keywords")
def keywords(limit: int = Query(20, ge=1, le=100), exclude_trends: bool = True):
    """Fastest-growing terms in the current window vs. their baseline average.
    By default, terms that are part of an active trend's phrase are left out (the
    trend already covers them), so this shows what *else* is moving."""
    d = config.section("detection")
    current = int(d.get("current_window_hours", 3))
    rows = _rows("""
        WITH w AS (
            SELECT word,
                   SUM(mentions) FILTER (WHERE bucket >= date_trunc('hour', now()) - make_interval(hours => :c - 1)) AS cur,
                   SUM(mentions) FILTER (WHERE bucket < date_trunc('hour', now()) - make_interval(hours => :c - 1)) AS base,
                   COUNT(DISTINCT platform) AS platforms
            FROM keyword_mentions
            WHERE bucket >= date_trunc('hour', now()) - make_interval(hours => :span - 1)
            GROUP BY word
        )
        SELECT word, COALESCE(cur, 0) AS current, COALESCE(base, 0) AS baseline, platforms,
               ROUND(((COALESCE(cur, 0) + 1.0) / (COALESCE(base, 0) * :c / GREATEST(:span - :c, 1) + 1.0))::numeric, 2)
                   AS growth
        FROM w WHERE COALESCE(cur, 0) > 0
        ORDER BY growth DESC, current DESC LIMIT :limit
    """, c=current, span=_span(), limit=limit * 25 if exclude_trends else limit * 5)
    from ai_models.trend_model import DEFAULT_IGNORE_TERMS

    ignore = set(DEFAULT_IGNORE_TERMS) | {t.lower() for t in d.get("ignore_terms", [])}
    rows = [r for r in rows if not set(r["word"].split()) & ignore]
    if exclude_trends:
        keys = [r["trend_key"] for r in _rows("SELECT trend_key FROM trends WHERE is_active AND trend_key IS NOT NULL")]
        tokens = [set(k.split()) for k in keys]
        compact = {k.replace(" ", "") for k in keys}
        rows = [r for r in rows if r["word"] not in compact and not any(set(r["word"].split()) & t for t in tokens)]
    # Collapse sub-phrases and hashtag forms into the fullest phrase with similar volume
    # ("retro", "pixel", "retropixelcameras" -> "retro pixel cameras").
    kept = []
    for r in sorted(rows, key=lambda r: (-len(r["word"].split()), -r["current"])):
        toks = set(r["word"].split())
        if not any((toks < set(k["word"].split()) and k["current"] >= 0.5 * r["current"])
                   or r["word"].replace(" ", "") == k["word"].replace(" ", "") for k in kept):
            kept.append(r)
    order = {id(r): i for i, r in enumerate(rows)}
    rows = sorted(kept, key=lambda r: order[id(r)])
    for r in rows:
        r["growth"] = float(r["growth"])
    return rows[:limit]


# --- pipeline -------------------------------------------------------------------

@app.get("/api/runs")
def runs(limit: int = Query(30, ge=1, le=200)):
    return _rows("""
        SELECT id, task, trigger, started_at, finished_at, status, summary, error,
               EXTRACT(EPOCH FROM (finished_at - started_at)) AS duration_s
        FROM pipeline_runs ORDER BY started_at DESC LIMIT :limit
    """, limit=limit)


@app.get("/api/config")
def settings():
    from workflows.pipeline import schedule_plan

    return {
        "settings": config.get_settings(),
        "schedule": [{"job": k, "every_minutes": v["minutes"]} for k, v in schedule_plan().items()],
    }


class RunRequest(BaseModel):
    task: str = "all"  # all | collect | pipeline


class _Runner:
    """Runs collection/pipeline in a background thread, one at a time."""

    def __init__(self):
        self._lock = threading.Lock()
        self.busy = False

    def start(self, task: str) -> bool:
        if not self._lock.acquire(blocking=False):
            return False
        self.busy = True
        threading.Thread(target=self._run, args=(task,), daemon=True).start()
        return True

    def _run(self, task: str):
        from workflows.pipeline import collect, run_pipeline

        try:
            if task in ("all", "collect"):
                collect("all", trigger="dashboard")
            if task in ("all", "pipeline"):
                run_pipeline(trigger="dashboard")
        except Exception as e:
            logger.error("Dashboard-triggered run failed: %s", e)
        finally:
            self.busy = False
            self._lock.release()


_runner = _Runner()


@app.post("/api/run", status_code=202)
def run(req: RunRequest):
    if req.task not in ("all", "collect", "pipeline"):
        raise HTTPException(400, "task must be all, collect or pipeline")
    if not _runner.start(req.task):
        raise HTTPException(409, "A run is already in progress")
    return {"started": req.task}


@app.get("/api/run")
def run_status():
    return {"running": _runner.busy}


# --- export --------------------------------------------------------------------

@app.get("/api/export.xlsx")
def export_xlsx():
    """All analytics in one Excel workbook (see analytics/export.py)."""
    import io

    from analytics.export import build_workbook

    buf = build_workbook(io.BytesIO())
    name = f"trend-analytics-{datetime.now(timezone.utc):%Y%m%d-%H%M}.xlsx"
    return Response(buf.getvalue(), headers={"Content-Disposition": f'attachment; filename="{name}"'},
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# --- alerts & ideas ------------------------------------------------------------

@app.get("/api/alerts")
def alerts(limit: int = Query(30, ge=1, le=200)):
    return _rows("""
        SELECT a.id, a.trend_id, a.alerted_at, a.channels_sent, a.alert_type, t.trend_name, t.platforms,
               (SELECT virality_probability FROM trend_predictions p
                 WHERE p.trend_id = a.trend_id AND p.predicted_at <= a.alerted_at
                 ORDER BY p.predicted_at DESC LIMIT 1) AS virality_at_alert,
               (SELECT trend_score FROM trend_predictions p
                 WHERE p.trend_id = a.trend_id AND p.predicted_at <= a.alerted_at
                 ORDER BY p.predicted_at DESC LIMIT 1) AS score_at_alert
        FROM alerts a JOIN trends t ON t.id = a.trend_id
        ORDER BY a.alerted_at DESC LIMIT :limit
    """, limit=limit)


@app.get("/api/ideas")
def ideas(limit: int = Query(30, ge=1, le=200)):
    return _rows("""
        SELECT c.*, t.trend_name FROM content_ideas c JOIN trends t ON t.id = c.trend_id
        ORDER BY c.generated_at DESC LIMIT :limit
    """, limit=limit)
