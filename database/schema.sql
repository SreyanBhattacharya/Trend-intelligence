-- Database Schema for Trend Intelligence Platform
-- Idempotent: runs on first container start (docker-entrypoint-initdb.d) and
-- via `python main.py init-db`, which also upgrades databases created from the
-- original schema.

CREATE TABLE IF NOT EXISTS posts (
    id SERIAL PRIMARY KEY,
    platform VARCHAR(50) NOT NULL,
    post_id VARCHAR(255) NOT NULL,
    author VARCHAR(255),
    title TEXT,
    body TEXT,
    url TEXT,
    posted_at TIMESTAMP WITH TIME ZONE,
    collected_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    likes INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    shares INTEGER DEFAULT 0,
    views BIGINT DEFAULT 0,
    engagement_score FLOAT DEFAULT 0.0,
    hashtags TEXT[],
    keywords TEXT[],
    processed BOOLEAN DEFAULT FALSE
);

-- Upgrades for databases created from the original schema.
-- post_id is only unique per platform, not globally.
ALTER TABLE posts DROP CONSTRAINT IF EXISTS posts_post_id_key;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS keywords TEXT[];
ALTER TABLE posts ALTER COLUMN views TYPE BIGINT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_posts_platform_post_id ON posts (platform, post_id);
CREATE INDEX IF NOT EXISTS idx_posts_posted_at ON posts (posted_at);
CREATE INDEX IF NOT EXISTS idx_posts_unprocessed ON posts (processed) WHERE processed = FALSE;
CREATE INDEX IF NOT EXISTS idx_posts_keywords ON posts USING GIN (keywords);

-- Lifetime keyword totals (kept for reporting).
CREATE TABLE IF NOT EXISTS keywords (
    id SERIAL PRIMARY KEY,
    word VARCHAR(255) NOT NULL,
    frequency INTEGER DEFAULT 1,
    first_seen TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE keywords ADD COLUMN IF NOT EXISTS first_seen TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;
CREATE UNIQUE INDEX IF NOT EXISTS idx_keywords_word ON keywords (word);

-- Hourly keyword counts. This time series is what spike detection and
-- prediction run on (lifetime totals alone cannot show a spike).
CREATE TABLE IF NOT EXISTS keyword_mentions (
    word VARCHAR(255) NOT NULL,
    bucket TIMESTAMP WITH TIME ZONE NOT NULL,
    platform VARCHAR(50) NOT NULL,
    mentions INTEGER NOT NULL DEFAULT 0,
    engagement DOUBLE PRECISION NOT NULL DEFAULT 0,
    PRIMARY KEY (word, bucket, platform)
);
CREATE INDEX IF NOT EXISTS idx_keyword_mentions_bucket ON keyword_mentions (bucket);

CREATE TABLE IF NOT EXISTS trends (
    id SERIAL PRIMARY KEY,
    trend_name VARCHAR(255) NOT NULL,
    description TEXT,
    detected_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    platform VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    related_post_ids INT[]
);
ALTER TABLE trends ADD COLUMN IF NOT EXISTS trend_key VARCHAR(255);
ALTER TABLE trends ADD COLUMN IF NOT EXISTS source VARCHAR(50) DEFAULT 'keyword_spike';
ALTER TABLE trends ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE trends ADD COLUMN IF NOT EXISTS platforms TEXT[];
ALTER TABLE trends ADD COLUMN IF NOT EXISTS z_score FLOAT DEFAULT 0.0;
UPDATE trends SET trend_key = lower(trend_name) || '#' || id WHERE trend_key IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_trends_trend_key ON trends (trend_key);

-- Hourly engagement snapshots per trend (input to the prediction model).
CREATE TABLE IF NOT EXISTS engagement_metrics (
    id SERIAL PRIMARY KEY,
    trend_id INTEGER REFERENCES trends(id) ON DELETE CASCADE,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    total_engagement INTEGER DEFAULT 0,
    growth_rate FLOAT DEFAULT 0.0
);
ALTER TABLE engagement_metrics ADD COLUMN IF NOT EXISTS mentions INTEGER DEFAULT 0;
ALTER TABLE engagement_metrics ALTER COLUMN total_engagement TYPE BIGINT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_engagement_trend_ts ON engagement_metrics (trend_id, timestamp);

CREATE TABLE IF NOT EXISTS trend_predictions (
    id SERIAL PRIMARY KEY,
    trend_id INTEGER REFERENCES trends(id) ON DELETE CASCADE,
    predicted_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    trend_score FLOAT DEFAULT 0.0,
    virality_probability FLOAT DEFAULT 0.0,  -- 0-100
    trend_momentum FLOAT DEFAULT 0.0,
    estimated_lifespan_days INTEGER DEFAULT 0
);
ALTER TABLE trend_predictions ADD COLUMN IF NOT EXISTS model VARCHAR(50);
CREATE INDEX IF NOT EXISTS idx_predictions_trend_time ON trend_predictions (trend_id, predicted_at DESC);

-- Most recent prediction per trend.
CREATE OR REPLACE VIEW latest_trend_predictions AS
SELECT DISTINCT ON (trend_id) *
FROM trend_predictions
ORDER BY trend_id, predicted_at DESC, id DESC;

CREATE TABLE IF NOT EXISTS content_ideas (
    id SERIAL PRIMARY KEY,
    trend_id INTEGER REFERENCES trends(id) ON DELETE CASCADE,
    generated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    suggested_format VARCHAR(100),
    suggested_caption TEXT,
    suggested_hashtags TEXT[],
    hook TEXT
);
ALTER TABLE content_ideas ADD COLUMN IF NOT EXISTS generator VARCHAR(50);

CREATE TABLE IF NOT EXISTS alerts (
    id SERIAL PRIMARY KEY,
    trend_id INTEGER REFERENCES trends(id) ON DELETE CASCADE,
    alerted_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    channels_sent TEXT[], -- e.g. ['slack', 'discord', 'email', 'console']
    alert_type VARCHAR(100)
);

-- One row per collection / pipeline run (shown on the dashboard's Pipeline page).
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id SERIAL PRIMARY KEY,
    task VARCHAR(50) NOT NULL,
    trigger VARCHAR(20) DEFAULT 'schedule',
    started_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP WITH TIME ZONE,
    status VARCHAR(20) DEFAULT 'running',
    summary JSONB,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_started ON pipeline_runs (started_at DESC);
