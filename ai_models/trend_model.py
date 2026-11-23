"""Trend detection models.

``detect_spikes`` compares each term's mentions in the *current* window with
its own history over the *baseline* window (split into windows of the same
size) and flags terms whose current volume is statistically unusual (z-score)
or several times their usual level (growth ratio).

``cluster_topics`` optionally groups recent posts into topics with BERTopic
(heavy, optional dependency in requirements-ml.txt).
"""
import datetime as dt
import logging
import math
from typing import Dict, Iterable, List, Optional, Sequence

logger = logging.getLogger(__name__)


def hour_fraction(now: Optional[dt.datetime] = None) -> float:
    """How much of the current (UTC) hour has elapsed, 0-1."""
    now = now or dt.datetime.now(dt.timezone.utc)
    return (now.minute * 60 + now.second) / 3600.0


def complete_partial_hour(hourly: Sequence[float], fraction: float) -> List[float]:
    """The newest hourly bucket is still filling up. Replace it with a trailing
    60-minute estimate (minutes so far this hour + the matching share of the
    previous hour), so a trend does not look like it is collapsing early in each
    hour. Unlike scaling the partial count up, this does not amplify noise."""
    values = [float(v) for v in hourly]
    if len(values) < 2 or fraction >= 0.999:
        return values
    values[-1] = values[-1] + values[-2] * (1.0 - max(fraction, 0.0))
    return values


def window_stats(hourly: Sequence[float], current_hours: int) -> Dict[str, float]:
    """Split an oldest-first hourly series into baseline windows + current window."""
    hourly = list(hourly)
    current = sum(hourly[-current_hours:]) if current_hours else 0.0
    history = hourly[:-current_hours] if current_hours else hourly
    windows = [sum(history[i:i + current_hours]) for i in range(0, len(history) - current_hours + 1, current_hours)]
    windows = windows or [0.0]
    mean = sum(windows) / len(windows)
    var = sum((w - mean) ** 2 for w in windows) / len(windows)
    std = math.sqrt(var)
    # +1 smoothing keeps brand-new terms (zero baseline) from producing infinite scores.
    z = (current - mean) / (std + 1.0)
    growth = (current + 1.0) / (mean + 1.0)
    return {"current": current, "baseline_mean": mean, "baseline_std": std, "z_score": z, "growth_ratio": growth}


DEFAULT_IGNORE_TERMS = {
    "week", "weekend", "today", "tonight", "thoughts", "thread", "discussion", "guide", "update", "video",
    "post", "people", "time", "year", "day", "best", "good", "great", "first", "last", "next", "free", "help",
}


def detect_spikes(term_series: Dict[str, Dict], current_hours: int = 3, min_mentions: int = 5,
                  z_threshold: float = 2.5, growth_threshold: float = 3.0, max_results: int = 25,
                  ignore_terms: Iterable[str] = DEFAULT_IGNORE_TERMS, representative_share: float = 0.4) -> List[Dict]:
    """
    ``term_series`` maps term -> {"hourly": [counts oldest..newest], "platforms": set/list, "engagement": float}.

    1. Flag terms whose current window is unusual vs. their own baseline.
    2. Replace each flagged term by its most specific *representative*: the longest
       candidate phrase containing all of its words that carries at least
       ``representative_share`` of its current volume ("voice" -> "ai voice clones").
    3. Remove duplicates (sub-phrases, hashtag forms like "aivoiceclones").
    """
    ignore = {t.lower() for t in (ignore_terms or [])}
    stats = {term: window_stats(data.get("hourly", []), current_hours) for term, data in term_series.items()}
    token_sets = {term: set(term.split()) for term in term_series}

    def as_spike(term: str, flagged_by: str) -> Dict:
        st, data = stats[term], term_series[term]
        return {"word": term, "frequency": int(st["current"]), "platforms": sorted(data.get("platforms", [])),
                "engagement": float(data.get("engagement", 0.0)), "flagged_by": flagged_by, **st}

    by_word: Dict[str, Dict] = {}
    for term, st in stats.items():
        if term in ignore or st["current"] < min_mentions:
            continue
        if not (st["z_score"] >= z_threshold or st["growth_ratio"] >= growth_threshold):
            continue
        rep = representative(term, stats, token_sets, ignore, representative_share)
        if rep not in by_word:
            by_word[rep] = as_spike(rep, term)

    spikes = sorted(by_word.values(), key=lambda s: (s["z_score"] * math.log1p(s["current"]), s["current"]),
                    reverse=True)
    return _dedupe_subphrases(spikes)[:max_results]


def representative(term: str, stats: Dict[str, Dict], token_sets: Dict[str, set], ignore: set,
                   share: float) -> str:
    """Longest phrase that contains ``term``'s words and explains >= share of its volume."""
    base_tokens, base = token_sets[term], stats[term]["current"]
    best, best_key = term, (len(base_tokens), base)
    for other, tokens in token_sets.items():
        if other in ignore or not base_tokens < tokens:
            continue
        cur = stats[other]["current"]
        if cur >= share * base:
            key = (len(tokens), cur)
            if key > best_key:
                best, best_key = other, key
    return best


def _dedupe_subphrases(spikes: List[Dict]) -> List[Dict]:
    """Drop 'pet filters' / 'filters' when 'ai pet filters' spikes with similar volume,
    and hashtag forms ('aipetfilters') of a phrase that is already a trend."""
    kept: List[Dict] = []
    for spike in sorted(spikes, key=lambda s: (-len(s["word"].split()), -s["current"])):
        tokens = set(spike["word"].split())
        compact = spike["word"].replace(" ", "")
        covered = any(
            (tokens < set(k["word"].split()) and k["current"] >= 0.4 * spike["current"])
            or compact == k["word"].replace(" ", "")
            for k in kept
        )
        if not covered:
            kept.append(spike)
    order = {id(s): i for i, s in enumerate(spikes)}
    return sorted(kept, key=lambda s: order[id(s)])


def merge_contained(spikes: List[Dict], post_terms: Dict[int, set], threshold: float = 0.8) -> List[Dict]:
    """Drop spikes that are just context around a bigger trend.

    ``post_terms`` maps post id -> set of terms for recent posts. A spike is dropped
    when at least ``threshold`` of the posts mentioning it also mention an already
    kept (larger) trend, e.g. "tested solar balcony" inside "solar balcony kits".
    Trends that merely share a word ("apple watch" vs "apple vision pro") survive
    because their posts are mostly different.
    """
    postings: Dict[str, set] = {s["word"]: set() for s in spikes}
    for pid, terms in post_terms.items():
        for term in terms:
            if term in postings:
                postings[term].add(pid)

    kept: List[Dict] = []
    for spike in sorted(spikes, key=lambda s: -s["current"]):
        mine = postings.get(spike["word"]) or set()
        contained = mine and any(
            len(mine & postings.get(k["word"], set())) >= threshold * len(mine) for k in kept
        )
        if not contained:
            kept.append(spike)
    order = {id(s): i for i, s in enumerate(spikes)}
    return sorted(kept, key=lambda s: order[id(s)])


def cluster_topics(posts_data: list, min_docs: int = 50) -> list:
    """Cluster posts using BERTopic if it is installed. Returns [] otherwise."""
    if not posts_data:
        return []
    try:
        from bertopic import BERTopic
    except ImportError:
        logger.info("BERTopic not installed (see requirements-ml.txt); skipping topic clustering.")
        return []

    docs, ids = [], []
    for p in posts_data:
        text = f"{p.get('title') or ''} {p.get('body') or ''}".strip()
        if text:
            docs.append(text)
            ids.append(p.get("id"))
    if len(docs) < min_docs:
        logger.info("Only %d docs; BERTopic needs at least %d. Skipping clustering.", len(docs), min_docs)
        return []

    try:
        topic_model = BERTopic(language="english", calculate_probabilities=False, verbose=False)
        topics, _ = topic_model.fit_transform(docs)
        clusters = []
        for _, row in topic_model.get_topic_info().iterrows():
            if row["Topic"] == -1:
                continue
            top_words = [w for w, _ in topic_model.get_topic(row["Topic"])][:3]
            clusters.append({
                "topic_id": int(row["Topic"]),
                "topic_name": " ".join(top_words),
                "size": int(row["Count"]),
                "post_ids": [pid for pid, t in zip(ids, topics) if t == row["Topic"]],
            })
        return clusters
    except Exception as e:
        logger.error("Error in topic clustering: %s", e)
        return []
