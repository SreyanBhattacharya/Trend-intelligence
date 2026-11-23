import logging
import time
from typing import Dict, List

from sqlalchemy import text

import config
from data_processing.cleaning_pipeline import normalize_term
from database.db_connection import get_engine

logger = logging.getLogger(__name__)

INSERT_POST = text("""
    INSERT INTO posts (platform, post_id, author, title, body, url, posted_at,
                       likes, comments, shares, views, hashtags)
    VALUES (:platform, :post_id, :author, :title, :body, :url, to_timestamp(:posted_at),
            :likes, :comments, :shares, :views, :hashtags)
    ON CONFLICT (platform, post_id) DO UPDATE SET
        likes = EXCLUDED.likes,
        comments = EXCLUDED.comments,
        shares = EXCLUDED.shares,
        views = EXCLUDED.views,
        collected_at = CURRENT_TIMESTAMP
""")


class DataCollectionAgent:
    """Collects raw posts from each source and stores them in ``posts``.

    API clients are created lazily so a missing optional library or credential
    only disables that one source.
    """

    def __init__(self):
        self.settings = config.section("data_collection")
        self._clients: Dict[str, object] = {}

    def _client(self, name: str):
        if name not in self._clients:
            if name == "reddit":
                from services.reddit_api import RedditService as cls
            elif name == "twitter":
                from services.twitter_api import TwitterService as cls
            elif name == "youtube":
                from services.youtube_api import YouTubeService as cls
            elif name == "google_trends":
                from services.google_trends_api import GoogleTrendsService as cls
            elif name == "demo":
                from services.demo_source import DemoService as cls
            else:
                raise ValueError(name)
            self._clients[name] = cls()
        return self._clients[name]

    # Backwards-compatible attribute access (agent.reddit, agent.twitter, ...)
    def __getattr__(self, item):
        if item in {"reddit", "twitter", "youtube", "google_trends", "demo"}:
            return self._client(item)
        raise AttributeError(item)

    def collect_reddit(self, subreddits: List[str] = None) -> int:
        subreddits = subreddits or self.settings.get("reddit_subreddits", [])
        limit = int(self.settings.get("reddit_posts_per_subreddit", 25))
        posts = []
        for sub in subreddits:
            posts.extend(self._client("reddit").fetch_top_posts(sub, limit=limit))
        return self._store("Reddit", posts)

    def collect_twitter(self, keywords: List[str] = None) -> int:
        keywords = keywords or self.settings.get("twitter_keywords", [])
        limit = int(self.settings.get("twitter_results_per_keyword", 20))
        posts = []
        for keyword in keywords:
            posts.extend(self._client("twitter").search_recent_tweets(query=keyword, limit=limit))
        return self._store("Twitter", posts)

    def collect_youtube(self) -> int:
        posts = self._client("youtube").fetch_trending_videos(
            max_results=int(self.settings.get("youtube_max_results", 30)),
            region_code=self.settings.get("youtube_region", "US"),
        )
        return self._store("YouTube", posts)

    def collect_google_trends(self) -> int:
        posts = self._client("google_trends").get_realtime_trending_searches(
            country=self.settings.get("google_trends_geo", "US"))
        return self._store("Google Trends", posts)

    def collect_demo(self, hours_back: int = 24) -> int:
        return self._store("Demo", self._client("demo").fetch_posts(hours_back=hours_back))

    def collect_all(self) -> Dict[str, int]:
        """Run every source once. Uses demo data when no real source is configured."""
        if config.demo_mode_enabled():
            logger.info("Demo mode: collecting synthetic posts (set DEMO_MODE=false to disable).")
            return {"demo": self.collect_demo()}
        results = {}
        for name, fn in (("reddit", self.collect_reddit), ("twitter", self.collect_twitter),
                         ("youtube", self.collect_youtube), ("google_trends", self.collect_google_trends)):
            try:
                results[name] = fn()
            except Exception as e:  # one broken source must not stop the others
                logger.error("%s collection failed: %s", name, e)
                results[name] = 0
        return results

    @staticmethod
    def _params(post: Dict) -> Dict:
        tags = [normalize_term(t) for t in (post.get("hashtags") or []) if t]
        return {
            "platform": post.get("platform") or "unknown",
            "post_id": str(post.get("post_id")),
            "author": str(post.get("author") or "unknown")[:250],
            "title": post.get("title") or "",
            "body": post.get("body") or "",
            "url": post.get("url") or "",
            "posted_at": float(post.get("posted_at") or time.time()),
            "likes": int(post.get("likes") or 0),
            "comments": int(post.get("comments") or 0),
            "shares": int(post.get("shares") or 0),
            "views": int(post.get("views") or 0),
            "hashtags": [t for t in tags if t],
        }

    def _store(self, label: str, posts: List[Dict]) -> int:
        engine = get_engine()
        if not posts or engine is None:
            logger.info("%s collection: nothing to store.", label)
            return 0
        rows = [self._params(p) for p in posts if p.get("post_id")]
        try:
            with engine.begin() as conn:
                conn.execute(INSERT_POST, rows)
            logger.info("%s collection finished. Stored %d posts.", label, len(rows))
            return len(rows)
        except Exception as e:
            logger.error("Failed to store %s posts: %s", label, e)
            return 0

    def _store_posts(self, posts: List[Dict]) -> int:
        """Kept for compatibility with older callers."""
        return self._store("Posts", posts)
