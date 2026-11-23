"""Central configuration loader.

Reads ``config/config.yaml`` (path resolved relative to the project root, so it
works no matter which directory the process is started from) and loads a
``.env`` file if one is present.
"""
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

import yaml

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.getenv("TREND_CONFIG_PATH", PROJECT_ROOT / "config" / "config.yaml"))

try:  # Load .env early so every module sees the same environment.
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env", override=False)
except ImportError:  # pragma: no cover - python-dotenv is in requirements
    pass

DEFAULTS: Dict[str, Any] = {
    "data_collection": {
        "reddit_subreddits": ["technology", "programming", "marketing", "startups"],
        "reddit_posts_per_subreddit": 25,
        "twitter_keywords": ["AI", "machine learning"],
        "twitter_results_per_keyword": 20,
        "youtube_region": "US",
        "youtube_max_results": 30,
        "google_trends_geo": "US",
    },
    "detection": {
        "current_window_hours": 3,
        "baseline_window_hours": 24,
        "min_mentions": 5,
        "z_score_threshold": 2.5,
        "growth_ratio_threshold": 3.0,
        "max_trends_per_run": 25,
        "trend_inactive_after_hours": 48,
    },
    "thresholds": {
        "trend_score_alert_threshold": 80,
        "virality_probability_alert_threshold": 70,
        "insight_virality_threshold": 60,
        "alert_cooldown_hours": 24,
    },
    "scheduling": {
        "reddit_scan_interval_minutes": 10,
        "twitter_scan_interval_minutes": 15,
        "youtube_scan_interval_minutes": 30,
        "google_trends_scan_interval_minutes": 60,
        "demo_scan_interval_minutes": 5,
        "pipeline_process_interval_minutes": 15,
    },
}


def _merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


@lru_cache(maxsize=1)
def get_settings() -> Dict[str, Any]:
    """Return platform settings merged over sane defaults."""
    file_settings: Dict[str, Any] = {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            file_settings = (yaml.safe_load(f) or {}).get("platform_settings", {}) or {}
    except FileNotFoundError:
        logger.warning("Config file %s not found, using defaults.", CONFIG_PATH)
    except Exception as e:  # malformed YAML etc.
        logger.warning("Failed to load %s (%s), using defaults.", CONFIG_PATH, e)
    return _merge(DEFAULTS, file_settings)


def section(name: str) -> Dict[str, Any]:
    return get_settings().get(name, {})


def as_percent(value: float) -> float:
    """Accept thresholds written either as a fraction (0.7) or a percentage (70)."""
    value = float(value)
    return value * 100.0 if 0 < value <= 1 else value


def demo_mode_enabled() -> bool:
    """Demo data is used when DEMO_MODE=true, or DEMO_MODE=auto (default) and no
    real data source has credentials configured."""
    mode = os.getenv("DEMO_MODE", "auto").strip().lower()
    if mode in {"1", "true", "yes", "on"}:
        return True
    if mode in {"0", "false", "no", "off"}:
        return False
    return not any(_has_real_value(os.getenv(k)) for k in (
        "REDDIT_CLIENT_ID", "TWITTER_BEARER_TOKEN", "YOUTUBE_API_KEY",
    ))


def _has_real_value(value) -> bool:
    """Treat the placeholders from .env.example as 'not configured'."""
    return bool(value) and not str(value).startswith("your_")


def env(name: str, default=None):
    """os.getenv that ignores .env.example placeholder values."""
    value = os.getenv(name)
    return value if _has_real_value(value) else default
