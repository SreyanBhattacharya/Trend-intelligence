"""Unit tests: text processing, models, demo data, agents' pure logic (no database)."""
import datetime as dt
import json
from types import SimpleNamespace

import pytest

import config
from agents.data_processing_agent import engagement_score, mention_bucket, post_terms
from agents.insight_agent import InsightAgent, hashtag
from agents.notification_agent import NotificationAgent
from ai_models.prediction_model import predict_virality, simple_prediction_heuristic
from ai_models.trend_model import detect_spikes, merge_contained, window_stats
from data_processing.cleaning_pipeline import clean_text, normalize_term
from data_processing.keyword_extraction import _fallback, extract_keywords
from database.db_connection import normalize_url
from services import demo_source
from services.google_trends_api import _parse_traffic, parse_rss


# --- text ---------------------------------------------------------------------

def test_clean_text():
    raw = "Check out this MASSIVE trend on @OpenAI! http://link.com #AI #Tech &amp; more"
    assert clean_text(raw) == "check out this massive trend on #ai #tech more"


def test_normalize_term():
    assert normalize_term("#AI_Pets") == "ai_pets"
    assert normalize_term("  Vibe-Coding  ") == "vibe coding"


@pytest.mark.parametrize("sentence", [
    "everyone is trying ai voice clones right now",
    "ai voice clones just blew up on my feed",
    "how to get started with ai voice clones",
    "why ai voice clones are suddenly everywhere",
])
def test_extract_keywords_finds_phrase_consistently(sentence):
    assert "ai voice clones" in extract_keywords(sentence)


def test_extract_keywords_fallback_without_spacy():
    terms = _fallback("the new ai pet filters are wild")
    assert "pet filters" in terms and "ai pet filters" in terms
    assert "the" not in terms


def test_extract_keywords_empty():
    assert extract_keywords("") == []


# --- spike detection ----------------------------------------------------------

def _series(hourly, platforms=("reddit",)):
    return {"hourly": hourly, "platforms": set(platforms), "engagement": 0.0}


def test_window_stats_flags_jump():
    st = window_stats([2] * 24 + [10, 15, 20], current_hours=3)
    assert st["current"] == 45 and st["baseline_mean"] == 6
    assert st["z_score"] > 2.5 and st["growth_ratio"] > 3


def test_detect_spikes_ignores_steady_terms():
    spikes = detect_spikes({
        "steady": _series([5] * 27),
        "rising": _series([0] * 22 + [1, 2, 4, 8, 16]),
        "tiny": _series([0] * 24 + [1, 1, 1]),
    })
    assert [s["word"] for s in spikes] == ["rising"]


def test_detect_spikes_promotes_specific_phrase_and_drops_hashtag_form():
    rising = [0] * 22 + [1, 2, 4, 8, 16]
    spikes = detect_spikes({
        "voice": _series(rising),
        "clones": _series(rising),
        "voice clones": _series(rising),
        "ai voice clones": _series(rising),
        "aivoiceclones": _series([0] * 24 + [2, 3, 5]),
        "week": _series(rising),  # generic word, ignored
    })
    assert [s["word"] for s in spikes] == ["ai voice clones"]


def test_merge_contained_drops_context_fragments_but_keeps_distinct_trends():
    spikes = [
        {"word": "solar balcony kits", "current": 50},
        {"word": "tested solar balcony", "current": 8},
        {"word": "apple watch", "current": 20},
    ]
    posts = {i: {"solar balcony kits"} for i in range(50)}
    posts.update({i: {"solar balcony kits", "tested solar balcony"} for i in range(8)})
    posts.update({100 + i: {"apple watch"} for i in range(20)})
    kept = [s["word"] for s in merge_contained(spikes, posts)]
    assert kept == ["solar balcony kits", "apple watch"]


# --- prediction ---------------------------------------------------------------

def _pts(values):
    return [{"timestamp": i, "mentions": v} for i, v in enumerate(values)]


def test_prediction_separates_rising_flat_and_fading():
    rising = predict_virality(_pts([0] * 17 + [1, 2, 4, 6, 9, 14, 22, 33, 40]), platform_count=3, use_prophet=False)
    flat = predict_virality(_pts([3, 2, 4, 3, 2, 3, 4, 3, 2, 3] * 2 + [3, 2, 4, 3, 3, 2]), platform_count=2,
                            use_prophet=False)
    fading = predict_virality(_pts([40] * 20 + [30, 20, 10, 5, 2]), platform_count=3, use_prophet=False)

    assert rising["virality_probability"] > 80 and rising["trend_score"] > 80
    assert flat["virality_probability"] < 30
    assert fading["virality_probability"] < 5 and fading["trend_momentum"] < 0
    for r in (rising, flat, fading):
        assert 0 <= r["trend_score"] <= 100 and 0 <= r["virality_probability"] <= 100


def test_prediction_empty_and_legacy_wrapper():
    assert predict_virality([])["virality_probability"] == 0
    legacy = simple_prediction_heuristic([
        {"timestamp": "2023-01-01T00:00:00Z", "total_engagement": 100},
        {"timestamp": "2023-01-01T01:00:00Z", "total_engagement": 500},
        {"timestamp": "2023-01-01T02:00:00Z", "total_engagement": 1200},
    ])
    assert legacy["trend_momentum"] > 0


# --- processing helpers -------------------------------------------------------

def test_engagement_score_bounds():
    assert engagement_score({"likes": 50, "comments": 10, "shares": 5, "views": 1000}) > 0
    assert engagement_score({"likes": 10 ** 9, "views": 0}) == 100
    assert engagement_score({}) == 0


def test_mention_bucket_uses_posted_time_unless_post_is_old():
    now = dt.datetime(2026, 1, 2, 12, 30, tzinfo=dt.timezone.utc)
    recent = {"posted_at": now - dt.timedelta(hours=5), "collected_at": now}
    old = {"posted_at": now - dt.timedelta(days=4), "collected_at": now}
    assert mention_bucket(recent) == dt.datetime(2026, 1, 2, 7, tzinfo=dt.timezone.utc)
    assert mention_bucket(old) == dt.datetime(2026, 1, 2, 12, tzinfo=dt.timezone.utc)


def test_post_terms_include_hashtags_and_google_query():
    terms = post_terms({"title": "Big news today", "body": "", "hashtags": ["#SolarKits"], "platform": "reddit"})
    assert "solarkits" in terms
    g = post_terms({"title": "World Series", "body": "", "hashtags": [], "platform": "google_trends"})
    assert "world series" in g


# --- demo data ----------------------------------------------------------------

def test_demo_posts_are_deterministic_and_never_in_future():
    now = dt.datetime(2026, 3, 1, 15, 20, tzinfo=dt.timezone.utc)
    a, b = demo_source.generate_posts(now=now), demo_source.generate_posts(now=now)
    assert [p["post_id"] for p in a] == [p["post_id"] for p in b]
    assert len({p["post_id"] for p in a}) == len(a)
    assert all(p["posted_at"] <= now.timestamp() for p in a)


def test_demo_always_has_a_rising_topic():
    base = dt.datetime(2026, 3, 1, tzinfo=dt.timezone.utc)
    for h in range(24):
        ages = [e["age"] for e in demo_source.emerging_topics_at(base + dt.timedelta(hours=h))]
        assert max(ages) >= 6


# --- config, URLs, Google Trends ----------------------------------------------

def test_threshold_scale_normalisation():
    assert config.as_percent(0.7) == 70
    assert config.as_percent(70) == 70


def test_placeholder_env_values_are_ignored(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "your_slack_webhook_url")
    assert config.env("SLACK_WEBHOOK_URL") is None


def test_normalize_url_pins_psycopg2():
    assert normalize_url("postgresql://u:p@h/db") == "postgresql+psycopg2://u:p@h/db"
    assert normalize_url("postgres://u:p@h/db") == "postgresql+psycopg2://u:p@h/db"


def test_google_trends_rss_parsing():
    xml = """<?xml version="1.0"?>
    <rss xmlns:ht="https://trends.google.com/trending/rss" version="2.0"><channel>
      <item><title>example topic</title><ht:approx_traffic>20K+</ht:approx_traffic>
        <pubDate>Mon, 23 Nov 2026 12:10:00 -0800</pubDate>
        <ht:news_item><ht:news_item_title>Story one</ht:news_item_title></ht:news_item></item>
      <item><title>second</title><ht:approx_traffic>1,000+</ht:approx_traffic></item>
    </channel></rss>"""
    posts = parse_rss(xml, "US")
    assert [p["title"] for p in posts] == ["example topic", "second"]
    assert posts[0]["views"] == 20000 and posts[0]["body"] == "Story one"
    assert _parse_traffic("2M+") == 2_000_000


# --- insight / notification ---------------------------------------------------

def test_hashtag():
    assert hashtag("ai voice clones") == "#AiVoiceClones"
    assert hashtag("AI pets") == "#AIPets"


def test_insight_template_without_llm():
    agent = InsightAgent()
    assert not agent.has_llm
    idea = agent.create_idea("solar balcony kits", "", ["reddit", "youtube"], [])
    assert idea["generator"] == "template"
    assert "#SolarBalconyKits" in idea["tags"] and "solar balcony kits" in idea["hook"]


def test_insight_uses_llm_json_and_falls_back_on_error():
    agent = InsightAgent()
    payload = {"format": "TikTok", "hook": "h", "caption": "c", "hashtags": ["#a", "b"]}
    message = SimpleNamespace(content=json.dumps(payload))
    agent.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kw: SimpleNamespace(choices=[SimpleNamespace(message=message)]))))
    idea = agent.create_idea("x", "", [], [])
    assert idea["fmt"] == "TikTok" and idea["tags"] == ["#a", "#b"] and idea["generator"] == agent.model

    def boom(**kw):
        raise RuntimeError("api down")
    agent.client.chat.completions.create = boom
    assert agent.create_idea("x", "", [], [])["generator"] == "template"


def test_notification_thresholds_and_format():
    agent = NotificationAgent()
    assert agent.virality_threshold == 70 and agent.trend_score_threshold == 80
    msg = agent._format_alert(
        {"trend_name": "ai pet filters", "platforms": ["reddit"], "platform": "reddit", "trend_score": 85.0,
         "virality_probability": 82.5, "estimated_lifespan_days": 3, "description": "spike"},
        {"suggested_format": "Reel", "hook": "h", "suggested_caption": "c", "suggested_hashtags": ["#a"]},
    )
    assert 'Trend: "ai pet filters"' in msg and "82.5%" in msg and "Hashtags: #a" in msg
