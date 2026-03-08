import os
import sys
import logging
import time
import yaml

# Ensure project root is in sys.path so imports like 'workflows' resolve correctly
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import sys
import os

# Add the project directory to sys.path so the 'workflows' package can be found
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workflows.pipeline import run_reddit_collection, run_twitter_collection, run_core_pipeline

logger = logging.getLogger(__name__)

# This serves as a standalone local lightweight scheduler fallback 
# if the Celery Beat worker isn't preferred for simple local testing.
# Best run via APScheduler.

def main():
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
    except ImportError:
        logger.error("APScheduler not installed. Please install it or use celery beat (docker-compose).")
        return
        
    logger.info("Starting standalone APScheduler...")
    scheduler = BlockingScheduler()
    
    reddit_interval = 10
    twitter_interval = 5
    pipeline_interval = 15
    
    try:
        with open("config/config.yaml", "r") as f:
            config = yaml.safe_load(f)
            sched = config.get("platform_settings", {}).get("scheduling", {})
            reddit_interval = sched.get("reddit_scan_interval_minutes", 10)
            twitter_interval = sched.get("twitter_scan_interval_minutes", 5)
            pipeline_interval = sched.get("pipeline_process_interval_minutes", 15)
    except Exception:
        pass

    scheduler.add_job(run_reddit_collection, 'interval', minutes=reddit_interval)
    scheduler.add_job(run_twitter_collection, 'interval', minutes=twitter_interval)
    scheduler.add_job(run_core_pipeline, 'interval', minutes=pipeline_interval)
    
    logger.info("Scheduler jobs added. Running...")
    scheduler.start()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
