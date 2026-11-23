import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Tests never touch real APIs or send alerts.
for key in ("REDDIT_CLIENT_ID", "TWITTER_BEARER_TOKEN", "YOUTUBE_API_KEY", "OPENAI_API_KEY",
            "SLACK_WEBHOOK_URL", "DISCORD_WEBHOOK_URL", "SMTP_USERNAME"):
    os.environ.pop(key, None)
os.environ["DEMO_MODE"] = "true"


@pytest.fixture
def db():
    """Fresh schema in the database at TEST_DATABASE_URL (skipped if unset).

    WARNING: drops and recreates the ``public`` schema of that database.
    """
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; skipping Postgres integration tests")

    from sqlalchemy import text

    from database.db_connection import init_db, reset_engine

    engine = reset_engine(url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    init_db()
    yield engine
    reset_engine()
