import os
import yaml
import logging
from celery import Celery
from celery.schedules import crontab

# Configure logging specifically for Celery workers
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Initialize Celery app
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
app = Celery("trend_pipeline", broker=REDIS_URL, backend=REDIS_URL)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    worker_concurrency=2, # Simple setup
)

# Load dynamic schedule intervals from config if present
reddit_interval = 10
twitter_interval = 5
google_interval = 60
pipeline_interval = 15

try:
    with open("config/config.yaml", "r") as f:
        config = yaml.safe_load(f)
        sched = config.get("platform_settings", {}).get("scheduling", {})
        reddit_interval = sched.get("reddit_scan_interval_minutes", 10)
        twitter_interval = sched.get("twitter_scan_interval_minutes", 5)
        google_interval = sched.get("google_trends_scan_interval_minutes", 60)
        pipeline_interval = sched.get("pipeline_process_interval_minutes", 15)
        
        platforms_config = config.get("platform_settings", {}).get("data_collection", {})
        subreddits = platforms_config.get("reddit_subreddits", ["technology", "startups"])
        keywords = platforms_config.get("twitter_keywords", ["AI", "machine learning"])
except Exception as e:
    logger.warning(f"Failed to load config.yaml for Celery, using defaults: {e}")
    subreddits = ["technology", "startups"]
    keywords = ["AI", "tech"]

app.conf.beat_schedule = {
    'collect-reddit-data': {
        'task': 'workflows.pipeline.run_reddit_collection',
        'schedule': crontab(minute=f'*/{reddit_interval}'),
    },
    'collect-twitter-data': {
        'task': 'workflows.pipeline.run_twitter_collection',
        'schedule': crontab(minute=f'*/{twitter_interval}'),
    },
    'run-main-processing-pipeline': {
        'task': 'workflows.pipeline.run_core_pipeline',
        'schedule': crontab(minute=f'*/{pipeline_interval}'),
    },
}

# --- Tasks ---

@app.task
def run_reddit_collection():
    from agents.data_collection_agent import DataCollectionAgent
    agent = DataCollectionAgent()
    agent.collect_reddit(subreddits)

@app.task
def run_twitter_collection():
    from agents.data_collection_agent import DataCollectionAgent
    agent = DataCollectionAgent()
    agent.collect_twitter(keywords)

@app.task
def run_core_pipeline():
    """Run the chain of processing, detection, prediction, insight, and notification."""
    logger.info("Starting primary core pipeline execution...")
    
    # 1. Processing
    from agents.data_processing_agent import DataProcessingAgent
    proc = DataProcessingAgent()
    proc.process_unprocessed_posts()
    
    # 2. Detection
    from agents.trend_detection_agent import TrendDetectionAgent
    detect = TrendDetectionAgent()
    detect.detect_trends()
    
    # 3. Prediction
    from agents.prediction_agent import PredictionAgent
    pred = PredictionAgent()
    pred.predict_trends()
    
    # 4. Insight Generation
    from agents.insight_agent import InsightAgent
    insight = InsightAgent()
    insight.generate_insights()
    
    # 5. Notification
    from agents.notification_agent import NotificationAgent
    notify = NotificationAgent()
    notify.check_and_notify()
    
    logger.info("Primary core pipeline execution finished.")
