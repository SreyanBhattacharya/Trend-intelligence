"""Trend scoring and virality prediction.

Input is a trend's hourly time series (mentions + engagement). The default
model is a transparent feature-based score:

* momentum      - slope of log(mentions) over the recent window (growth per hour)
* acceleration  - change in that slope (is growth speeding up or stalling?)
* volume        - recent mentions (log scaled)
* spread        - number of platforms the trend appears on
* surprise      - z-score of the current window vs. the trend's own baseline

These are combined into a 0-100 trend score and a logistic virality
probability (0-100). The weights are hand-tuned, not learned: there is no
labelled "went viral" data yet. Once alerts have been reviewed, the weights in
``WEIGHTS`` are the place to calibrate.

If Prophet is installed (requirements-ml.txt) and there is enough history, its
24h forecast is blended in to estimate where volume is heading.
"""
import logging
import math
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

WEIGHTS = {
    "bias": -4.0,
    "momentum": 6.0,       # per unit of log-growth per hour
    "acceleration": 2.0,   # clipped to +/-0.3 (noisy on short series)
    "volume": 0.3,         # per unit of log1p(recent mentions)
    "spread": 0.4,         # per extra platform
    "surprise": 0.3,       # per z-score unit (capped at 10)
}


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _slope(y: np.ndarray) -> float:
    if len(y) < 2:
        return 0.0
    x = np.arange(len(y), dtype=float)
    return float(np.polyfit(x, y, 1)[0])


def compute_features(series: List[Dict[str, Any]], platform_count: int = 1, recent_hours: int = 6,
                     z_score: Optional[float] = None) -> Dict[str, float]:
    mentions = np.array([float(p.get("mentions", p.get("total_engagement", 0)) or 0) for p in series])
    if mentions.size == 0:
        mentions = np.zeros(1)
    log_m = np.log1p(mentions)
    recent = log_m[-recent_hours:]
    momentum = _slope(recent)
    half = max(2, len(recent) // 2)
    acceleration = _slope(recent[-half:]) - _slope(recent[:half]) if len(recent) >= 4 else 0.0
    volume = float(np.log1p(mentions[-3:].sum()))

    if z_score is None:
        hist = mentions[:-3]
        cur = mentions[-3:].sum()
        windows = [hist[i:i + 3].sum() for i in range(0, max(len(hist) - 2, 0), 3)] or [0.0]
        z_score = (cur - np.mean(windows)) / (np.std(windows) + 1.0)

    return {
        "momentum": momentum,
        "acceleration": float(min(max(acceleration, -0.3), 0.3)),
        "volume": volume,
        "spread": float(max(platform_count, 1)),
        "surprise": float(min(max(z_score, -5.0), 10.0)),
    }


def score_features(f: Dict[str, float]) -> Dict[str, float]:
    w = WEIGHTS
    logit = (w["bias"] + w["momentum"] * f["momentum"] + w["acceleration"] * f["acceleration"]
             + w["volume"] * f["volume"] + w["spread"] * (f["spread"] - 1) + w["surprise"] * f["surprise"])
    prob = _sigmoid(logit) * 100.0

    # Trend score: how strong the trend is *now* (volume, growth, novelty, reach).
    score = (
        35 * _sigmoid(4 * f["momentum"])                     # growth
        + 25 * min(f["volume"] / math.log1p(150), 1.0)       # size
        + 25 * min(max(f["surprise"], 0) / 8.0, 1.0)         # novelty
        + 15 * min((f["spread"] - 1) / 2.0, 1.0)             # cross-platform reach
    )
    return {"trend_score": round(min(max(score, 0.0), 100.0), 2), "virality_probability": round(prob, 2)}


def estimate_lifespan_days(f: Dict[str, float]) -> int:
    """Rough guess: fast, accelerating, multi-platform trends last longer."""
    if f["momentum"] <= 0:
        return 1
    days = 1 + 2 * f["momentum"] * 10 * (1 + 0.5 * (f["spread"] - 1))
    if f["acceleration"] < 0:
        days *= 0.6
    return int(min(max(round(days), 1), 14))


def _prophet_growth(series: List[Dict[str, Any]]) -> Optional[float]:
    """Ratio of forecast next-24h volume to last-24h volume, or None."""
    if len(series) < 12:
        return None
    try:
        import pandas as pd
        from prophet import Prophet
    except ImportError:
        return None
    try:
        df = pd.DataFrame({
            "ds": pd.to_datetime([p["timestamp"] for p in series], utc=True).tz_localize(None),
            "y": [float(p.get("mentions", 0) or 0) for p in series],
        })
        m = Prophet(daily_seasonality=False, weekly_seasonality=False, yearly_seasonality=False)
        m.fit(df)
        forecast = m.predict(m.make_future_dataframe(periods=24, freq="h"))
        future = forecast["yhat"].tail(24).clip(lower=0).sum()
        past = df["y"].tail(24).sum()
        return float((future + 1) / (past + 1))
    except Exception as e:
        logger.warning("Prophet forecast failed: %s", e)
        return None


def predict_virality(engagement_data: List[Dict[str, Any]], platform_count: int = 1,
                     z_score: Optional[float] = None, use_prophet: bool = True) -> Dict[str, Any]:
    """
    Score a trend from its hourly series (oldest first). Each point is a dict with
    ``timestamp`` and ``mentions`` (``total_engagement`` is accepted for older callers).
    """
    if not engagement_data:
        return {"trend_score": 0.0, "virality_probability": 0.0, "trend_momentum": 0.0,
                "estimated_lifespan_days": 0, "model": "empty"}

    f = compute_features(engagement_data, platform_count=platform_count, z_score=z_score)
    model = "heuristic"
    growth = _prophet_growth(engagement_data) if use_prophet else None
    if growth is not None:
        # Blend the forecast's growth expectation into momentum (log-ratio spread over 24h).
        f["momentum"] = 0.5 * f["momentum"] + 0.5 * (math.log(growth) / 24.0)
        model = "heuristic+prophet"

    result = score_features(f)
    result.update({
        "trend_momentum": round(f["momentum"], 4),
        "estimated_lifespan_days": estimate_lifespan_days(f),
        "model": model,
        "features": f,
    })
    return result


def simple_prediction_heuristic(engagement_data: list) -> Dict[str, Any]:
    """Backwards-compatible wrapper (no Prophet)."""
    return predict_virality(engagement_data, use_prophet=False)
