import logging
from bs4 import BeautifulSoup
import requests
from typing import List, Dict

logger = logging.getLogger(__name__)

class ScraperService:
    def __init__(self):
        # We can configure Playwright here if fully needed, but BeautifulSoup/requests
        # is a lighter alternative for basic scraping fallbacks where APIs aren't available.
        # Note: TikTok scraping is notoriously difficult and usually requires rotating proxies
        # and real-browser automation like Playwright. We'll outline a generic structure here.
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        logger.info("Scraper service initialized.")

    def fetch_page_content(self, url: str) -> str:
        """Fetch raw HTML content using requests as fallback."""
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            return response.text
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return ""

    def scrape_basic_meta_tags(self, url: str) -> Dict:
        """Scrape Open Graph and basic meta tags from a URL to extract trend context."""
        html = self.fetch_page_content(url)
        if not html:
            return {}
            
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            title = soup.find('title')
            title = title.text if title else ""
            
            description = soup.find('meta', attrs={'name': 'description'})
            description = description['content'] if description else ""
            
            og_title = soup.find('meta', property='og:title')
            og_title = og_title['content'] if og_title else ""
            
            return {
                "title": og_title or title,
                "description": description,
                "url": url
            }
        except Exception as e:
            logger.error(f"Error parsing meta tags for {url}: {e}")
            return {}
