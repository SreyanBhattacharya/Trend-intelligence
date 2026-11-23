"""Synthetic social-media feed for running the platform without API keys.

Every hour bucket is generated deterministically from its timestamp, so calling
``generate_posts`` repeatedly is idempotent (same post ids, upserted) while
new hours keep adding fresh data as real time passes.

Two "emerging" topic slots run on 12-hour cycles offset by 6 hours. Within a
cycle a topic grows roughly exponentially and spreads from Reddit to Twitter to
YouTube, then the next topic takes over. This gives the detector a realistic
mix of steady background chatter, rising trends and fading ones.
"""
import datetime as dt
import random
from typing import Dict, List, Optional

BACKGROUND_TOPICS = [
    "python", "javascript", "kubernetes", "cloud costs", "remote work", "startup funding",
    "product management", "cybersecurity", "open source", "seo tips", "email marketing", "linux",
    "data engineering", "react", "iphone", "electric cars",
]

EMERGING_TOPICS = [
    "ai pet filters", "vibe coding agents", "solar balcony kits", "quiet quitting apps",
    "retro pixel cameras", "ai voice clones", "micro saas tools", "smart ring trackers",
    "rust game engines", "lofi study streams",
]

BACKGROUND_TEMPLATES = [
    "Thoughts on {t} this week?",
    "A practical guide to {t}",
    "What is your current setup for {t}?",
    "Unpopular opinion about {t}",
    "Lessons learned from a year of {t}",
    "Weekly discussion thread: {t}",
]

EMERGING_TEMPLATES = [
    "Everyone is trying {t} right now",
    "{T} just blew up on my feed",
    "How to get started with {t}",
    "I tested {t} so you do not have to",
    "Why {t} are suddenly everywhere",
    "Spent the weekend with {t}",
    "{T}, explained simply",
]

PLATFORMS = ["reddit", "twitter", "youtube"]
CYCLE_HOURS = 12


def _hour_index(bucket: dt.datetime) -> int:
    return int(bucket.timestamp() // 3600)


def emerging_topics_at(bucket: dt.datetime) -> List[Dict]:
    """Which emerging topics are active in this hour, and how far into their cycle."""
    h = _hour_index(bucket)
    active = []
    for slot in (0, 1):
        shifted = h + slot * (CYCLE_HOURS // 2)
        cycle, age = divmod(shifted, CYCLE_HOURS)
        topic = EMERGING_TOPICS[(cycle * 2 + slot) % len(EMERGING_TOPICS)]
        active.append({"topic": topic, "age": age, "slot": slot})
    return active


def _make_post(rng: random.Random, bucket: dt.datetime, idx: str, topic: str, platform: str,
               emerging: bool, boost: float) -> Dict:
    templates = EMERGING_TEMPLATES if emerging else BACKGROUND_TEMPLATES
    text = rng.choice(templates).format(t=topic, T=topic.capitalize())
    posted = bucket + dt.timedelta(seconds=rng.randint(0, 3599))
    views = int(rng.randint(200, 2000) * boost)
    likes = int(views * rng.uniform(0.02, 0.08) * (1.5 if emerging else 1.0))
    tag = topic.replace(" ", "")
    return {
        "platform": platform,
        "post_id": f"demo-{_hour_index(bucket)}-{idx}",
        "author": f"demo_user_{rng.randint(1, 500)}",
        "title": text if platform != "twitter" else "",
        "body": text if platform == "twitter" else "",
        "url": f"https://example.com/demo/{_hour_index(bucket)}/{idx}",
        "posted_at": posted.timestamp(),
        "likes": likes,
        "comments": int(likes * rng.uniform(0.05, 0.3)),
        "shares": int(likes * rng.uniform(0.0, 0.2)) if platform == "twitter" else 0,
        "views": views,
        "hashtags": [f"#{tag}"] if emerging and rng.random() < 0.5 else [],
    }


def posts_for_hour(bucket: dt.datetime) -> List[Dict]:
    bucket = bucket.replace(minute=0, second=0, microsecond=0)
    rng = random.Random(_hour_index(bucket))
    posts = []

    for i, topic in enumerate(BACKGROUND_TOPICS):
        for j in range(rng.randint(1, 4)):
            posts.append(_make_post(rng, bucket, f"b{i}-{j}", topic, rng.choice(PLATFORMS), False, 1.0))

    for em in emerging_topics_at(bucket):
        age = em["age"]
        count = min(40, round(1.55 ** age))
        platforms = PLATFORMS[: 1 + (age >= 3) + (age >= 6)]
        for j in range(count):
            posts.append(_make_post(rng, bucket, f"e{em['slot']}-{j}", em["topic"], rng.choice(platforms),
                                    True, 1.0 + age / 4))
    return posts


def generate_posts(now: Optional[dt.datetime] = None, hours_back: int = 24) -> List[Dict]:
    """All demo posts from ``hours_back`` hours ago up to ``now`` (inclusive)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    current = now.replace(minute=0, second=0, microsecond=0)
    posts = []
    for back in range(hours_back, -1, -1):
        bucket = current - dt.timedelta(hours=back)
        posts.extend(p for p in posts_for_hour(bucket) if p["posted_at"] <= now.timestamp())
    return posts


class DemoService:
    """Same shape as the real API services."""

    def fetch_posts(self, hours_back: int = 24) -> List[Dict]:
        return generate_posts(hours_back=hours_back)
