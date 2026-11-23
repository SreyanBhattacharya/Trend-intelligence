# Trend Intelligence Platform

An autonomous trend-intelligence pipeline. It monitors social platforms, detects emerging trends early, scores
their momentum and virality, generates content ideas, and sends alerts.

It runs out of the box with **no API keys**: if no data source is configured, it uses a built-in synthetic feed
where new topics rise and fade over time, so every stage produces real output.

## Documentation

| Doc | Read it for |
|---|---|
| [docs/RUNBOOK.md](docs/RUNBOOK.md) | step-by-step: start, stop, add API keys, tune, update, test, troubleshoot |
| [docs/LEARNING_GUIDE.md](docs/LEARNING_GUIDE.md) | how everything works end to end: technologies, data sources, formulas, design decisions, interview Q&A |
| [docs/PROJECT.md](docs/PROJECT.md) | full project description, API, data model, limitations and the **roadmap** |
| [docs/DASHBOARD_GUIDE.md](docs/DASHBOARD_GUIDE.md) | every dashboard page and metric, plus the Excel analytics export |
| [docs/architecture.md](docs/architecture.md) | short architecture summary |

![Dashboard](docs/images/overview.png)

## How it works

| Agent | What it does |
|---|---|
| **DataCollectionAgent** | Pulls posts from Reddit (PRAW), X/Twitter (Tweepy), YouTube (Data API, trending chart) and Google Trends ("Trending now" RSS, no key needed). Uses the demo feed when nothing is configured. |
| **DataProcessingAgent** | Cleans text, extracts keywords and 2–3-word phrases (spaCy plus n-grams), scores engagement, and builds an **hourly keyword time series** (`keyword_mentions`). |
| **TrendDetectionAgent** | Compares each term's last 3h against its own 24h baseline (z-score / growth ratio). It picks the most specific phrase ("voice" → "ai voice clones"), merges context fragments and hashtag forms, and upserts deduplicated trends. Optional BERTopic clustering. |
| **PredictionAgent** | Records each trend's hourly series (`engagement_metrics`) and computes momentum, acceleration, volume, cross-platform spread and novelty. These give a 0–100 **trend score** and a 0–100 **virality probability**, plus a lifespan estimate. If Prophet is installed, its 24h forecast is blended in. |
| **InsightAgent** | Generates a format, hook, caption and hashtags for high-potential trends with OpenAI (JSON mode), or a template when no key is set. |
| **NotificationAgent** | Alerts via Slack, Discord or email (console as a fallback) when both thresholds are met, with a 24h cooldown per trend. |

Celery Beat (or the built-in APScheduler loop) runs collection and the pipeline on the intervals in
`config/config.yaml`. See [docs/architecture.md](docs/architecture.md) for details.

## Dashboard

A web dashboard at **http://localhost:8000** shows everything the platform produces:

* **Overview**: a gauge for the top trend's virality, trend-strength bars, pipeline health, the trending-now list
  with platform split, a 3-hour momentum dot chart, the latest alerts and content ideas, rising keywords, and
  hourly data intake.
* **Trends**: every trend with sparkline, score, virality, momentum and lifespan. Click a trend for details:
  mentions per hour, virality history, content idea and top posts.
* **Datasets**: browse and search collected posts by platform and keyword.
* **Pipeline**: totals for each stage over the last 24h, run history, data sources, alert channels and schedule.
* **Alerts**: the alert log, plus content ideas with copy-to-clipboard.

The **Run pipeline** button collects data and runs the full pipeline on demand. The **download** icon exports
**all analytics in one Excel workbook** (10 sheets with charts; also `python main.py export`). The page refreshes every 30
seconds. It is one static file (`web/index.html`, no build step) served by a FastAPI app (`api/server.py`), whose
JSON API is documented at http://localhost:8000/docs.

## Quick start (Docker)

```bash
cp .env.example .env        # optional: add any API keys you have
docker compose up -d --build
docker compose logs -f worker
```

This starts PostgreSQL, Redis, a one-off `migrate` job (creates or upgrades the schema), a Celery worker, Celery
Beat and the dashboard (http://localhost:8000). With no keys, demo data arrives every 5 minutes and the pipeline runs every 15. Alerts print in the worker log.

Requires Docker Compose v2.24+ (for the optional `.env` file). To include Prophet/BERTopic in the image:
`docker compose build --build-arg INSTALL_ML=true`.

## Local development (no Docker)

You need Python 3.11+ and a PostgreSQL database (`DATABASE_URL`, default
`postgresql://trend_user:trend_password@localhost:5432/trend_db`).

```bash
pip install -r requirements-dev.txt          # add requirements-ml.txt for Prophet/BERTopic
python -m spacy download en_core_web_sm

python main.py init-db                       # create / upgrade schema
python main.py run-once                      # collect + full pipeline once
python main.py report                        # show top trends
python main.py schedule                      # run continuously (no Redis/Celery needed)
python main.py web                           # dashboard on http://localhost:8000
python main.py export                        # all analytics -> trend-analytics-<time>.xlsx
python main.py collect reddit                # one source: reddit|twitter|youtube|google_trends|demo
```

## Configuration

* **`.env`**: API keys, webhooks and SMTP (see `.env.example`). Placeholder values like `your_...` count as unset.
  `DEMO_MODE=auto|true|false` controls the synthetic feed (`auto` = only when no source has credentials).
* **`config/config.yaml`**: subreddits, keywords, detection windows and sensitivity, alert thresholds and schedules.
  Thresholds are on a 0–100 scale (fractions such as `0.7` are also accepted).

Notes on sources:
* X/Twitter recent search requires a paid API tier.
* Google Trends uses the public RSS feed. `pytrends` is only a fallback, because Google retired the endpoint it used.

## Tests

```bash
pytest                                       # unit tests
TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/trend_test pytest   # + Postgres integration tests
```

The integration tests **drop and recreate the `public` schema** of the test database. CI (GitHub Actions) runs lint,
unit and integration tests against a Postgres service, then builds the Docker image.

## Output example

```
==================================================
ALERT: NEW VIRAL TREND DETECTED
==================================================
Trend: "solar balcony kits"
Platforms: reddit, twitter, youtube
Trend Score: 87.3
Virality Probability: 90.0%
Estimated Lifespan: ~9 day(s)
Signal: 59 mentions in the last 3h vs. a baseline of 3.0 per 3h (z=7.7, x15.0) across reddit, twitter, youtube.

Suggested Content Idea:
Format: Carousel post (Instagram/LinkedIn)
Hook: "Stop scrolling if you haven't seen solar balcony kits yet."
Caption: "Everyone on Reddit, X/Twitter and YouTube is suddenly talking about solar balcony kits. Here's what it is, why people care, and how to jump in before it peaks."
Hashtags: #SolarBalconyKits #Trending #Reddit
==================================================
```

## Limitations

The virality model is a hand-weighted logistic score over transparent features, not a trained classifier: there is
no labelled "went viral" data yet. Once alerts have been reviewed, the weights in `ai_models/prediction_model.py`
(`WEIGHTS`) are the place to calibrate.
