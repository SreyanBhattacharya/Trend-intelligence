import logging

import praw

import config
from typing import List, Dict

logger = logging.getLogger(__name__)


class RedditService:
    def __init__(self):
        self.client_id = config.env("REDDIT_CLIENT_ID")
        self.client_secret = config.env("REDDIT_CLIENT_SECRET")
        self.user_agent = config.env("REDDIT_USER_AGENT", "trend_intel_agent:v1.0")

        try:
            if self.client_id and self.client_secret:
                self.reddit = praw.Reddit(
                    client_id=self.client_id,
                    client_secret=self.client_secret,
                    user_agent=self.user_agent,
                    read_only=True
                )
                logger.info("Reddit API client initialized.")
            else:
                logger.info("Reddit API credentials not found. Reddit source disabled.")
                self.reddit = None
        except Exception as e:
            logger.error(f"Failed to initialize Reddit client: {e}")
            self.reddit = None

    def fetch_top_posts(self, subreddit_name: str, limit: int = 50, time_filter: str = 'day') -> List[Dict]:
        """Fetch top posts from a subreddit within a time period."""
        if not self.reddit:
            logger.debug("Reddit API not initialized. Returning empty list.")
            return []

        try:
            subreddit = self.reddit.subreddit(subreddit_name)
            posts = []
            for submission in subreddit.top(time_filter=time_filter, limit=limit):
                # Basic processing to extract what we need
                post_data = {
                    "platform": "reddit",
                    "post_id": submission.id,
                    "author": submission.author.name if submission.author else "deleted",
                    "title": submission.title,
                    "body": submission.selftext,
                    "url": submission.url,
                    "posted_at": submission.created_utc,  # This is a timestamp float
                    "likes": submission.score,  # Upvotes
                    "comments": submission.num_comments,
                    "shares": 0,  # Not easily available without deeper scraping
                    "views": submission.view_count or 0,
                    "subreddit": subreddit_name
                }
                posts.append(post_data)
            return posts
        except Exception as e:
            logger.error(f"Error fetching Reddit posts from {subreddit_name}: {e}")
            return []
