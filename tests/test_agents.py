import pytest
from data_processing.cleaning_pipeline import clean_text
from ai_models.prediction_model import simple_prediction_heuristic
from data_processing.keyword_extraction import extract_keywords

def test_clean_text():
    raw_text = "Check out this MASSIVE trend on @OpenAI! http://link.com #AI #Tech"
    cleaned = clean_text(raw_text)
    assert "http" not in cleaned
    assert "openai" not in cleaned
    assert "check out this massive trend on #ai #tech" == cleaned

def test_simple_prediction_heuristic():
    data = [
        {"timestamp": "2023-01-01T00:00:00Z", "total_engagement": 100},
        {"timestamp": "2023-01-01T01:00:00Z", "total_engagement": 500},
        {"timestamp": "2023-01-01T02:00:00Z", "total_engagement": 1200}
    ]
    result = simple_prediction_heuristic(data)
    assert result["trend_score"] > 50
    assert result["virality_probability"] > 30

def test_extract_keywords_fallback():
    # Will use fallback if spacy model is missing, or spacy if present
    text = "The quick brown fox jumps over the lazy dog."
    keywords = extract_keywords(text)
    assert isinstance(keywords, list)
