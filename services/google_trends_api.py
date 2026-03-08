import logging
from pytrends.request import TrendReq
from typing import List, Dict
import pandas as pd

logger = logging.getLogger(__name__)

class GoogleTrendsService:
    def __init__(self):
        try:
            self.pytrends = TrendReq(hl='en-US', tz=360)
            logger.info("Google Trends client initialized.")
        except Exception as e:
            logger.error(f"Failed to initialize Google Trends client: {e}")
            self.pytrends = None

    def get_realtime_trending_searches(self, country: str = 'US') -> List[Dict]:
        """Fetch real-time trending searches from Google Trends."""
        if not self.pytrends:
            return []
            
        try:
            trending_df = self.pytrends.trending_searches(pn=country.lower())
            
            trends = []
            if not trending_df.empty:
                for idx, row in trending_df.iterrows():
                    # The DataFrame usually has one column containing the query string (index 0)
                    query = row[0]
                    trend_data = {
                        "platform": "google_trends",
                        "trend_name": query,
                        "description": f"Trending search in {country}",
                        "rank": idx + 1
                    }
                    trends.append(trend_data)
            return trends
        except Exception as e:
            logger.error(f"Error fetching Google Trends real-time searches: {e}")
            return []
