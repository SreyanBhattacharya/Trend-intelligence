import os
import logging
import tweepy
from typing import List, Dict

logger = logging.getLogger(__name__)

class TwitterService:
    def __init__(self):
        self.bearer_token = os.getenv("TWITTER_BEARER_TOKEN")
        
        try:
            if self.bearer_token:
                self.client = tweepy.Client(bearer_token=self.bearer_token)
                logger.info("Twitter API client initialized.")
            else:
                logger.warning("Twitter API credentials not found. Twitter service will be mocked/disabled.")
                self.client = None
        except Exception as e:
            logger.error(f"Failed to initialize Twitter client: {e}")
            self.client = None

    def search_recent_tweets(self, query: str, limit: int = 100) -> List[Dict]:
        """Search recent tweets matching a query."""
        if not self.client:
            logger.warning("Twitter API not initialized. Returning empty list.")
            return []
            
        try:
            # We request extra fields to get engagement metrics and author info
            response = self.client.search_recent_tweets(
                query=query,
                max_results=limit,
                tweet_fields=['created_at', 'public_metrics', 'author_id', 'text', 'entities'],
                user_fields=['username']
            )
            
            if not response.data:
                return []
                
            posts = []
            for tweet in response.data:
                metrics = tweet.public_metrics
                
                # Extract hashtags if any
                hashtags = []
                if tweet.entities and 'hashtags' in tweet.entities:
                    hashtags = [tag['tag'] for tag in tweet.entities['hashtags']]
                
                post_data = {
                    "platform": "twitter",
                    "post_id": str(tweet.id),
                    "author": str(tweet.author_id), # We would need to resolve this to username in a real app or use includes
                    "title": "", # Twitter doesn't really have titles, just body
                    "body": tweet.text,
                    "url": f"https://twitter.com/user/status/{tweet.id}",
                    "posted_at": tweet.created_at.timestamp(), # convert to POSIX timestamp for consistency
                    "likes": metrics.get('like_count', 0),
                    "comments": metrics.get('reply_count', 0),
                    "shares": metrics.get('retweet_count', 0),
                    "views": metrics.get('impression_count', 0),
                    "hashtags": hashtags
                }
                posts.append(post_data)
            return posts
        except Exception as e:
            logger.error(f"Error fetching Twitter posts for query '{query}': {e}")
            return []
