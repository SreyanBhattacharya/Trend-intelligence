import os
import logging
from googleapiclient.discovery import build
from typing import List, Dict
import datetime

logger = logging.getLogger(__name__)

class YouTubeService:
    def __init__(self):
        self.api_key = os.getenv("YOUTUBE_API_KEY")
        
        try:
            if self.api_key:
                self.youtube = build('youtube', 'v3', developerKey=self.api_key)
                logger.info("YouTube API client initialized.")
            else:
                logger.warning("YouTube API credentials not found. YouTube service will be mocked/disabled.")
                self.youtube = None
        except Exception as e:
            logger.error(f"Failed to initialize YouTube client: {e}")
            self.youtube = None

    def fetch_trending_videos(self, max_results: int = 50, region_code: str = 'US') -> List[Dict]:
        """Fetch current trending YouTube videos."""
        if not self.youtube:
            logger.warning("YouTube API not initialized. Returning empty list.")
            return []
            
        try:
            request = self.youtube.videos().list(
                part="snippet,contentDetails,statistics",
                chart="mostPopular",
                regionCode=region_code,
                maxResults=max_results
            )
            response = request.execute()
            
            posts = []
            for item in response.get('items', []):
                snippet = item['snippet']
                stats = item.get('statistics', {})
                
                # Parse ISO 8601 string to timestamp
                dt = datetime.datetime.fromisoformat(snippet['publishedAt'].replace('Z', '+00:00'))
                
                post_data = {
                    "platform": "youtube",
                    "post_id": item['id'],
                    "author": snippet.get('channelTitle', ''),
                    "title": snippet.get('title', ''),
                    "body": snippet.get('description', ''),
                    "url": f"https://www.youtube.com/watch?v={item['id']}",
                    "posted_at": dt.timestamp(),
                    "likes": int(stats.get('likeCount', 0)),
                    "comments": int(stats.get('commentCount', 0)),
                    "shares": 0, # Not provided by API
                    "views": int(stats.get('viewCount', 0)),
                    "hashtags": snippet.get('tags', [])
                }
                posts.append(post_data)
            return posts
        except Exception as e:
            logger.error(f"Error fetching YouTube trending videos: {e}")
            return []
