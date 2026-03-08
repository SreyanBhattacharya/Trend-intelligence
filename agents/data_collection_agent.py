import logging
import time
from sqlalchemy import text
from database.db_connection import engine
from services.reddit_api import RedditService
from services.twitter_api import TwitterService
from services.youtube_api import YouTubeService

logger = logging.getLogger(__name__)

class DataCollectionAgent:
    """Agent responsible for collecting raw data from various APIs and storing it."""
    def __init__(self):
        self.reddit = RedditService()
        self.twitter = TwitterService()
        self.youtube = YouTubeService()
        
    def collect_reddit(self, subreddits: list):
        logger.info(f"Starting Reddit collection for {subreddits}")
        all_posts = []
        for sub in subreddits:
            posts = self.reddit.fetch_top_posts(sub, limit=20)
            all_posts.extend(posts)
        
        self._store_posts(all_posts)
        logger.info(f"Reddit collection finished. Stored {len(all_posts)} posts.")

    def collect_twitter(self, keywords: list):
        logger.info(f"Starting Twitter collection for {keywords}")
        all_posts = []
        for keyword in keywords:
            posts = self.twitter.search_recent_tweets(query=keyword, limit=20)
            all_posts.extend(posts)
        
        self._store_posts(all_posts)
        logger.info(f"Twitter collection finished. Stored {len(all_posts)} posts.")

    def collect_youtube(self):
        logger.info("Starting YouTube collection")
        posts = self.youtube.fetch_trending_videos(max_results=30)
        self._store_posts(posts)
        logger.info(f"YouTube collection finished. Stored {len(posts)} videos.")

    def _store_posts(self, posts: list):
        if not posts or not engine:
            return
            
        insert_query = text("""
            INSERT INTO posts (platform, post_id, author, title, body, url, posted_at, likes, comments, shares, views, hashtags)
            VALUES (:platform, :post_id, :author, :title, :body, :url, to_timestamp(:posted_at), :likes, :comments, :shares, :views, :hashtags)
            ON CONFLICT (platform, post_id) DO UPDATE SET
                likes = EXCLUDED.likes,
                comments = EXCLUDED.comments,
                shares = EXCLUDED.shares,
                views = EXCLUDED.views,
                collected_at = CURRENT_TIMESTAMP
        """)
        
        try:
            with engine.begin() as conn:
                for post in posts:
                    # Provide defaults for missing keys
                    params = {
                        "platform": post.get("platform"),
                        "post_id": str(post.get("post_id")),
                        "author": post.get("author", "unknown")[:250],
                        "title": post.get("title", ""),
                        "body": post.get("body", ""),
                        "url": post.get("url", ""),
                        "posted_at": post.get("posted_at", time.time()),
                        "likes": post.get("likes", 0),
                        "comments": post.get("comments", 0),
                        "shares": post.get("shares", 0),
                        "views": post.get("views", 0),
                        "hashtags": post.get("hashtags", [])
                    }
                    conn.execute(insert_query, params)
        except Exception as e:
            logger.error(f"Failed to store raw posts in DB: {e}")
