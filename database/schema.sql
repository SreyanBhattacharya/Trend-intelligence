-- Database Schema for Trend Intelligence Platform

CREATE TABLE IF NOT EXISTS posts (
    id SERIAL PRIMARY KEY,
    platform VARCHAR(50) NOT NULL,
    post_id VARCHAR(255) UNIQUE NOT NULL,
    author VARCHAR(255),
    title TEXT,
    body TEXT,
    url TEXT,
    posted_at TIMESTAMP WITH TIME ZONE,
    collected_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    likes INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    shares INTEGER DEFAULT 0,
    views INTEGER DEFAULT 0,
    engagement_score FLOAT DEFAULT 0.0,
    hashtags TEXT[],
    processed BOOLEAN DEFAULT FALSE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_posts_platform_post_id ON posts (platform, post_id);
CREATE INDEX IF NOT EXISTS idx_posts_posted_at ON posts (posted_at);

CREATE TABLE IF NOT EXISTS trends (
    id SERIAL PRIMARY KEY,
    trend_name VARCHAR(255) NOT NULL,
    description TEXT,
    detected_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    platform VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    related_post_ids INT[]
);

CREATE TABLE IF NOT EXISTS keywords (
    id SERIAL PRIMARY KEY,
    word VARCHAR(255) NOT NULL,
    frequency INTEGER DEFAULT 1,
    last_seen TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_keywords_word ON keywords (word);

CREATE TABLE IF NOT EXISTS engagement_metrics (
    id SERIAL PRIMARY KEY,
    trend_id INTEGER REFERENCES trends(id) ON DELETE CASCADE,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    total_engagement INTEGER DEFAULT 0,
    growth_rate FLOAT DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS trend_predictions (
    id SERIAL PRIMARY KEY,
    trend_id INTEGER REFERENCES trends(id) ON DELETE CASCADE,
    predicted_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    trend_score FLOAT DEFAULT 0.0,
    virality_probability FLOAT DEFAULT 0.0,
    trend_momentum FLOAT DEFAULT 0.0,
    estimated_lifespan_days INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS content_ideas (
    id SERIAL PRIMARY KEY,
    trend_id INTEGER REFERENCES trends(id) ON DELETE CASCADE,
    generated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    suggested_format VARCHAR(100),
    suggested_caption TEXT,
    suggested_hashtags TEXT[],
    hook TEXT
);

CREATE TABLE IF NOT EXISTS alerts (
    id SERIAL PRIMARY KEY,
    trend_id INTEGER REFERENCES trends(id),
    alerted_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    channels_sent TEXT[], -- e.g. ['slack', 'discord', 'email']
    alert_type VARCHAR(100)
);
