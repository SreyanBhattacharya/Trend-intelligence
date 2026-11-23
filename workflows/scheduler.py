"""Standalone scheduler for local runs without Celery/Redis.

    python workflows/scheduler.py      (or: python main.py schedule)

Runs every job once at start-up, then on the intervals from config.yaml.
"""
import datetime as dt
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workflows.pipeline import schedule_plan  # noqa: E402

logger = logging.getLogger(__name__)


def main():
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
    except ImportError:
        logger.error("APScheduler not installed. Run 'pip install apscheduler' or use Celery (docker-compose).")
        return

    scheduler = BlockingScheduler(timezone="UTC")
    now = dt.datetime.now(dt.timezone.utc)
    for i, (name, job) in enumerate(sorted(schedule_plan().items(), key=lambda kv: kv[0] == "run-core-pipeline")):
        # Collect first, then run the pipeline shortly after start-up.
        scheduler.add_job(job["task"], "interval", minutes=float(job["minutes"]), id=name, name=name,
                          next_run_time=now + dt.timedelta(seconds=5 * i), max_instances=1, coalesce=True)
        logger.info("Scheduled %s every %s min", name, job["minutes"])

    logger.info("Scheduler running. Press Ctrl+C to stop.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    main()
