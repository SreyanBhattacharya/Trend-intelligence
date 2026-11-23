"""Google Trends "Trending now" collector.

Uses Google's public RSS feed (no API key). The ``pytrends`` library's
``trending_searches`` endpoint was retired by Google and pytrends itself is no
longer maintained, so it is only tried as a fallback when installed.

Each trending search is emitted as a post (platform ``google_trends``) so it
flows through the same processing / detection pipeline as social posts.
"""
import datetime as dt
import logging
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import Dict, List

import requests

logger = logging.getLogger(__name__)

RSS_URL = "https://trends.google.com/trending/rss?geo={geo}"
HT_NS = "{https://trends.google.com/trending/rss}"


def _parse_traffic(value: str) -> int:
    """'200,000+' / '20K+' / '2M+' -> int."""
    if not value:
        return 0
    v = value.strip().upper().replace(",", "").rstrip("+")
    mult = 1
    if v.endswith("K"):
        mult, v = 1_000, v[:-1]
    elif v.endswith("M"):
        mult, v = 1_000_000, v[:-1]
    try:
        return int(float(v) * mult)
    except ValueError:
        return 0


def parse_rss(xml_text: str, geo: str = "US") -> List[Dict]:
    root = ET.fromstring(xml_text)
    posts = []
    for rank, item in enumerate(root.iter("item"), start=1):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        pub = item.findtext("pubDate")
        try:
            posted = parsedate_to_datetime(pub).timestamp() if pub else dt.datetime.now(dt.timezone.utc).timestamp()
        except (TypeError, ValueError):
            posted = dt.datetime.now(dt.timezone.utc).timestamp()
        news_titles = [n.findtext(f"{HT_NS}news_item_title") or "" for n in item.findall(f"{HT_NS}news_item")]
        day = dt.datetime.fromtimestamp(posted, dt.timezone.utc).strftime("%Y%m%d")
        posts.append({
            "platform": "google_trends",
            "post_id": f"{geo}-{day}-{re.sub(r'[^a-z0-9]+', '-', title.lower())}"[:250],
            "author": "google_trends",
            "title": title,
            "body": " ".join(news_titles),
            "url": f"https://trends.google.com/trends/explore?q={requests.utils.quote(title)}&geo={geo}",
            "posted_at": posted,
            "likes": 0,
            "comments": 0,
            "shares": 0,
            "views": _parse_traffic(item.findtext(f"{HT_NS}approx_traffic") or ""),
            "hashtags": [],
            "rank": rank,
        })
    return posts


class GoogleTrendsService:
    def __init__(self, timeout: int = 15):
        self.timeout = timeout

    def get_realtime_trending_searches(self, country: str = "US") -> List[Dict]:
        """Fetch currently trending searches for a country (ISO code, e.g. 'US', 'IN')."""
        geo = country.upper()
        try:
            resp = requests.get(RSS_URL.format(geo=geo), timeout=self.timeout,
                                headers={"User-Agent": "Mozilla/5.0 trend-intelligence"})
            resp.raise_for_status()
            posts = parse_rss(resp.text, geo)
            logger.info("Fetched %d Google Trends items for %s.", len(posts), geo)
            return posts
        except Exception as e:
            logger.warning("Google Trends RSS fetch failed (%s); trying pytrends fallback.", e)
            return self._pytrends_fallback(geo)

    def _pytrends_fallback(self, geo: str) -> List[Dict]:
        try:
            from pytrends.request import TrendReq

            names = {"US": "united_states", "IN": "india", "GB": "united_kingdom"}
            df = TrendReq(hl="en-US", tz=0).trending_searches(pn=names.get(geo, "united_states"))
            now = dt.datetime.now(dt.timezone.utc)
            return [{
                "platform": "google_trends",
                "post_id": f"{geo}-{now:%Y%m%d}-{re.sub(r'[^a-z0-9]+', '-', str(q).lower())}"[:250],
                "author": "google_trends", "title": str(q), "body": "", "url": "",
                "posted_at": now.timestamp(), "views": 0, "hashtags": [], "rank": i + 1,
            } for i, q in enumerate(df.iloc[:, 0].tolist())]
        except Exception as e:
            logger.error("Google Trends unavailable: %s", e)
            return []
