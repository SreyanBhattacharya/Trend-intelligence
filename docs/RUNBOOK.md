# Runbook: running Trend Intelligence day to day

These are step-by-step instructions for starting, using, configuring, updating and troubleshooting the platform.
Commands are for **Windows PowerShell**; on macOS/Linux use the same commands, except `copy` becomes `cp`
and `venv\Scripts\activate` becomes `source venv/bin/activate`.

> Always work in the folder that is connected to GitHub (for example `C:\Users\<you>\Downloads\JAUB\repo`).
> Running two copies of the project at once makes them fight over the same ports (5432, 6379, 8000).

---

## 1. One-time setup

| You need | Check it with | Get it from |
|---|---|---|
| Git | `git --version` | git-scm.com |
| Docker Desktop (WSL 2 / Linux containers) | `docker info` (must show a **Server** section) | docker.com/products/docker-desktop |
| A copy of the repo | `git log --oneline -1` inside the folder | `git clone https://github.com/SreyanBhattacharya/Trend-intelligence.git repo` |

```powershell
cd C:\Users\<you>\Downloads\JAUB\repo
copy .env.example .env        # only the first time; then edit .env to add keys (section 4)
```

Tip: in Docker Desktop, go to **Settings → General** and turn on **Start Docker Desktop when you sign in**. The
containers are set to `restart: unless-stopped`, so the platform comes back by itself after a reboot.

---

## 2. Start, use, stop

### Start
```powershell
cd C:\Users\<you>\Downloads\JAUB\repo
docker compose up -d --build
docker compose ps
```
Expected: `db`, `redis`, `worker`, `scheduler` and `web` show **running**, and `migrate` shows **exited (0)**
because it creates or upgrades the database and then stops.

Open **http://localhost:8000**. On a fresh database, click **Run pipeline** to fill the dashboard straight away.
Otherwise the scheduler collects every 5 minutes (demo mode) and runs the pipeline every 15 minutes.

### Everyday commands
| What | Command |
|---|---|
| Open the dashboard | http://localhost:8000 |
| Browse the JSON API | http://localhost:8000/docs |
| Run collection + pipeline now | dashboard **Run pipeline** button, or `docker compose exec worker python main.py run-once` |
| Top trends in the terminal | `docker compose exec worker python main.py report` |
| Export all analytics to Excel | dashboard download icon (top right), or see below |
| Watch the worker | `docker compose logs -f worker` (Ctrl+C stops watching, not the app) |
| Watch the dashboard server | `docker compose logs -f web` |
| Status of every container | `docker compose ps` |

Exporting from the command line writes the file inside the container. Copy it out like this:
```powershell
docker compose exec worker python main.py export /tmp/analytics.xlsx
docker compose cp worker:/tmp/analytics.xlsx .\analytics.xlsx
```

### Stop / restart / reset
| What | Command | Data kept? |
|---|---|---|
| Stop everything | `docker compose down` | yes |
| Start again | `docker compose up -d` | yes |
| Restart after editing `.env` or `config.yaml` | `docker compose up -d --force-recreate` | yes |
| Rebuild after changing Python code or requirements | `docker compose up -d --build` | yes |
| **Wipe the database** and start clean | `docker compose down -v` then `docker compose up -d --build` | **no** |

---

## 3. Demo mode vs. real data

* **Demo mode** (the default with no API keys) generates realistic synthetic posts. New topics rise and fade on
  12-hour cycles, so every feature produces output. The dashboard's status chip shows **Demo data**.
* As soon as **any** source key (Reddit, X or YouTube) is set in `.env`, demo mode switches off and only real
  sources are collected. Google Trends is always collected in live mode and needs no key. The chip shows
  **Live sources**.
* To force a mode, set `DEMO_MODE=true` or `DEMO_MODE=false` in `.env`.

---

## 4. Adding API keys (`.env`)

Edit `.env` in the repo folder, then run `docker compose up -d --force-recreate`. Leave a line as its
`your_...` placeholder to keep that integration off.

| Integration | Variables | Where to get them |
|---|---|---|
| Reddit | `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT` | reddit.com/prefs/apps → *create app* → type **script**. The ID is under the app name. |
| YouTube | `YOUTUBE_API_KEY` | Google Cloud Console → new project → enable **YouTube Data API v3** → Credentials → API key |
| X / Twitter | `TWITTER_BEARER_TOKEN` | developer.x.com → project → Bearer token. Recent search needs a **paid** tier. |
| OpenAI (AI-written ideas) | `OPENAI_API_KEY`, optional `OPENAI_MODEL` (default `gpt-4o-mini`) | platform.openai.com → API keys |
| Slack alerts | `SLACK_WEBHOOK_URL` | Slack → Apps → Incoming Webhooks → add to a channel |
| Discord alerts | `DISCORD_WEBHOOK_URL` | Discord channel → Edit → Integrations → Webhooks → New |
| Email alerts | `SMTP_SERVER`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `FROM_EMAIL`, `ALERT_TO_EMAIL` | For Gmail: turn on 2-step verification, then create an **App password** |

Never commit `.env`; it is already in `.gitignore`. The dashboard's **Pipeline** page shows which sources and
channels it detects as configured.

---

## 5. Tuning behaviour (`config/config.yaml`)

After editing, run `docker compose up -d --force-recreate`.

| Setting | Effect |
|---|---|
| `data_collection.reddit_subreddits`, `twitter_keywords`, `youtube_region`, `google_trends_geo` | What gets collected. For India, use `youtube_region: "IN"` and `google_trends_geo: "IN"`. |
| `detection.current_window_hours` / `baseline_window_hours` | The "now" window compared with the normal level (default 3h vs. 24h) |
| `detection.min_mentions`, `z_score_threshold`, `growth_ratio_threshold` | Sensitivity. Lower values give more (and noisier) trends. |
| `detection.ignore_terms` (list) | Extra generic words never to treat as trends |
| `thresholds.trend_score_alert_threshold`, `virality_probability_alert_threshold` | When alerts fire (both must be met) |
| `thresholds.insight_virality_threshold` | When content ideas are generated |
| `thresholds.alert_cooldown_hours` | Minimum time between two alerts for the same trend |
| `scheduling.*_interval_minutes` | How often each job runs |

---

## 6. Updating the code and pushing to GitHub

```powershell
cd C:\Users\<you>\Downloads\JAUB\repo
git pull                                  # get the latest from GitHub first
# ...edit files...
docker compose up -d --build              # rebuild and run with your changes
git add -A
git commit -m "Describe what you changed"
git push
```
Every push runs CI (lint, 38 tests against Postgres, Docker build). Check the results at
https://github.com/SreyanBhattacharya/Trend-intelligence/actions.

To apply a `.patch` file someone sends you: `git am path\to\file.patch`, then `git push`.

---

## 7. Running the tests on your machine

You need Python 3.11+ installed. The tests use the Postgres container.

```powershell
cd C:\Users\<you>\Downloads\JAUB\repo
python -m venv venv
venv\Scripts\activate
pip install -r requirements-dev.txt
python -m spacy download en_core_web_sm

docker compose up -d db
docker compose exec db createdb -U trend_user trend_test     # once
$env:TEST_DATABASE_URL = "postgresql://trend_user:trend_password@localhost:5432/trend_test"
pytest -v
flake8 .
```
The integration tests **wipe** the `trend_test` database each time. Never point `TEST_DATABASE_URL` at `trend_db`.

---

## 8. Running without Docker (optional)

You need Python 3.11+ and PostgreSQL. You can run just Postgres in Docker with `docker compose up -d db`.

```powershell
venv\Scripts\activate
python main.py init-db        # create / upgrade tables
python main.py run-once       # one full collection + pipeline run
python main.py web            # dashboard on http://localhost:8000 (keep this window open)
python main.py schedule       # in a second window: keeps collecting and running on schedule (no Redis needed)
```
Other CLI commands: `python main.py collect reddit` (one source), `python main.py report`,
`python main.py export analytics.xlsx`.

---

## 9. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `failed to connect to the docker API ... dockerDesktopLinuxEngine` | Docker Desktop not running | Start Docker Desktop, wait for **Engine running**, check `docker info` |
| `docker compose ps` shows no `web` | You're in the old folder or on an old version | `cd` into the `repo` folder, `git log` should show the dashboard commit, then `up -d --build` |
| `port is already allocated` (5432 / 6379 / 8000) | Another copy or a local Postgres/Redis is running | `docker ps`, then `docker stop <name>` (or `docker compose down` in the other folder) |
| Dashboard banner: *Can't reach the database* | `db` container stopped | `docker compose up -d db`, then refresh |
| Dashboard empty | Fresh database, nothing collected yet | Click **Run pipeline** |
| No alerts appear | No trend meets *both* thresholds yet (normal early on) | Wait for the next cycle, or lower thresholds in `config.yaml` |
| A container keeps restarting | It is crashing on start | `docker compose logs <service> --tail 50` and read the last error |
| Build fails on `pip install` | Network hiccup | Run `docker compose build --no-cache` and then `up -d` again |
| `git am` says *not a git repository* | Wrong folder | `cd` into `repo` first |
| `git push` rejected (*fetch first*) | GitHub has newer commits | `git pull --rebase`, then `git push` |
| Real source collects 0 posts | Missing/invalid key, or X free tier | `docker compose logs worker` and look for warnings from that source |

**Health check:** http://localhost:8000/api/health returns `{"status": "ok", "database": true}` when the
dashboard can reach Postgres.
