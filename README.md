# Trend Intelligence Platform

A fully autonomous AI-powered trend intelligence platform that continuously monitors social media platforms, detects emerging trends early, predicts virality probability, and generates actionable content ideas.

## Features
- **Data Collection Agent**: Connects to multi-platform APIs (Reddit, Twitter, YouTube, etc.) to ingest raw text and engagement metrics.
- **Data Processing Agent**: Cleans data and uses NLP (spaCy) to extract keywords.
- **Trend Detection Agent**: Detects keyword frequency spikes and clusters common topics using AI (Mocked BERTopic / simple frequency analysis).
- **Prediction Agent**: Scores trend momentum and virality probability (Mocked Prophet integration).
- **Insight Agent**: Uses LLMs (OpenAI) to generate actionable social media content (hooks, captions, hashtags) for high-potential trends.
- **Notification Agent**: Dispatches instant alerts via Slack/Email.
- **Autonomous Scheduling**: Runs periodically using Celery and Redis.

## Prerequisites
- Docker and docker-compose
- Python 3.11+ (if running locally without Docker)
- API Keys for Reddit, Twitter, YouTube, Slack (Optional, can run in mock modes without keys).

## Setup Instructions

1. **Clone and Configure Env**:
   ```bash
   cp .env.example .env
   # Edit .env with your actual API keys.
   ```

2. **Run via Docker Compose**:
   ```bash
   docker-compose up -d --build
   ```
   This will spin up:
   - PostgreSQL Database (`trend_db`)
   - Redis Broker
   - Celery Worker
   - Celery Beat Scheduler

3. **Check Logs**:
   To see the platform autonomously collecting and analyzing data:
   ```bash
   docker-compose logs -f worker
   ```

## Local Development (No Docker)
1. Install dependencies: `pip install -r requirements.txt`
2. Download NLP model: `python -m spacy download en_core_web_sm`
3. Run the standalone scheduler loop: `python workflows/scheduler.py`
4. Run tests: `pytest tests/`

## Output Example
```
==================================================
ALERT: NEW VIRAL TREND DETECTED
==================================================
Trend: "AI pet filters"
Platform: aggregated
Trend Score: 85.0
Virality Probability: 82.5%

Suggested Content Idea:
Format: TikTok/Reels
Hook: "Stop scrolling if you don't know about AI pet filters."
Caption: "POV: You just discovered the AI pet filters trend! Spike detected in keyword usage."
Hashtags: #AIpetfilters #AITrend #Viral
==================================================
```
