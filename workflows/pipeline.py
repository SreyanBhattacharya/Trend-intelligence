"""Pipeline orchestration: plain functions plus Celery tasks/beat schedule.

``run_pipeline`` runs processing -> detection -> prediction -> insight ->
notification once and returns a summary; the Celery tasks and the standalone
scheduler both call these same functions.
"""
import json
import logging
import os
import sys
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Dict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from celery import Celery  # noqa: E402

import config  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


# --- Run log -------------------------------------------------------------------

@contextmanager
def recorded_run(task: str, trigger: str):
    """Record a run in ``pipeline_runs``. Logging failures never break the run itself."""
    from sqlalchemy import text

    from database.db_connection import get_engine

    engine, run_id, result = get_engine(), None, {}
    try:
        with engine.begin() as conn:
            run_id = conn.execute(text(
                "INSERT INTO pipeline_runs (task, trigger) VALUES (:t, :tr) RETURNING id"),
                {"t": task, "tr": trigger}).scalar()
    except Exception as e:
        logger.debug("Could not record run start: %s", e)

    def finish(status, summary=None, error=None):
        if run_id is None:
            return
        try:
            with engine.begin() as conn:
                conn.execute(text("""UPDATE pipeline_runs SET finished_at = CURRENT_TIMESTAMP, status = :s,
                                     summary = CAST(:sum AS JSONB), error = :e WHERE id = :id"""),
                             {"s": status, "sum": json.dumps(summary or {}), "e": error, "id": run_id})
        except Exception as e:
            logger.debug("Could not record run end: %s", e)

    try:
        yield result
    except Exception as e:
        finish("failed", result, str(e)[:2000])
        raise
    finish("success", result)


# --- Plain functions -----------------------------------------------------------

def collect(source: str = "all", trigger: str = "schedule") -> Dict[str, int]:
    from agents.data_collection_agent import DataCollectionAgent

    with recorded_run(f"collect:{source}", trigger) as out:
        agent = DataCollectionAgent()
        result = agent.collect_all() if source == "all" else {source: getattr(agent, f"collect_{source}")()}
        out.update(result)
    return result


def run_pipeline(trigger: str = "schedule") -> Dict[str, int]:
    with recorded_run("pipeline", trigger) as out:
        summary = _run_pipeline()
        out.update(summary)
    return summary


def _run_pipeline() -> Dict[str, int]:
    """Process -> detect -> predict -> generate insights -> notify."""
    from agents.data_processing_agent import DataProcessingAgent
    from agents.insight_agent import InsightAgent
    from agents.notification_agent import NotificationAgent
    from agents.prediction_agent import PredictionAgent
    from agents.trend_detection_agent import TrendDetectionAgent

    logger.info("Starting core pipeline execution...")
    summary = {
        "posts_processed": DataProcessingAgent().process_unprocessed_posts(),
        "trends_detected": len(TrendDetectionAgent().detect_trends()),
        "trends_scored": len(PredictionAgent().predict_trends()),
        "ideas_generated": len(InsightAgent().generate_insights()),
        "alerts_sent": len(NotificationAgent().check_and_notify()),
    }
    logger.info("Core pipeline finished: %s", summary)
    return summary


# --- Celery --------------------------------------------------------------------

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
app = Celery("trend_pipeline", broker=REDIS_URL, backend=REDIS_URL)
app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    worker_concurrency=2,
    result_expires=3600,
    broker_connection_retry_on_startup=True,
)


@app.task(name="workflows.pipeline.run_reddit_collection")
def run_reddit_collection():
    return collect("reddit")


@app.task(name="workflows.pipeline.run_twitter_collection")
def run_twitter_collection():
    return collect("twitter")


@app.task(name="workflows.pipeline.run_youtube_collection")
def run_youtube_collection():
    return collect("youtube")


@app.task(name="workflows.pipeline.run_google_trends_collection")
def run_google_trends_collection():
    return collect("google_trends")


@app.task(name="workflows.pipeline.run_demo_collection")
def run_demo_collection():
    return collect("demo")


@app.task(name="workflows.pipeline.run_core_pipeline")
def run_core_pipeline():
    return run_pipeline()


def schedule_plan() -> Dict[str, Dict]:
    """Which collection jobs to run and how often (minutes). Shared by Celery beat and APScheduler."""
    s = config.section("scheduling")
    plan = {"run-core-pipeline": {"task": run_core_pipeline,
                                  "minutes": s.get("pipeline_process_interval_minutes", 15)}}
    if config.demo_mode_enabled():
        plan["collect-demo-data"] = {"task": run_demo_collection, "minutes": s.get("demo_scan_interval_minutes", 5)}
    else:
        if config.env("REDDIT_CLIENT_ID"):
            plan["collect-reddit-data"] = {"task": run_reddit_collection,
                                           "minutes": s.get("reddit_scan_interval_minutes", 10)}
        if config.env("TWITTER_BEARER_TOKEN"):
            plan["collect-twitter-data"] = {"task": run_twitter_collection,
                                            "minutes": s.get("twitter_scan_interval_minutes", 15)}
        if config.env("YOUTUBE_API_KEY"):
            plan["collect-youtube-data"] = {"task": run_youtube_collection,
                                            "minutes": s.get("youtube_scan_interval_minutes", 30)}
        plan["collect-google-trends"] = {"task": run_google_trends_collection,  # no key needed
                                         "minutes": s.get("google_trends_scan_interval_minutes", 60)}
    return plan


# timedelta schedules work for any interval (crontab '*/60' is invalid).
app.conf.beat_schedule = {
    name: {"task": job["task"].name, "schedule": timedelta(minutes=float(job["minutes"]))}
    for name, job in schedule_plan().items()
}
