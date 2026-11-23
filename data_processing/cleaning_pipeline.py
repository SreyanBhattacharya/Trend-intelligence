import html
import re

_URL = re.compile(r"https?://\S+|www\.\S+")
_MENTION = re.compile(r"@\w+")
_NON_WORD = re.compile(r"[^\w\s#]")
_SPACES = re.compile(r"\s+")


def clean_text(text: str) -> str:
    """Clean and normalize social media text for NLP processing."""
    if not text:
        return ""

    text = html.unescape(text).lower()
    text = _URL.sub(" ", text)
    text = _MENTION.sub(" ", text)
    # Keep letters, digits, underscores, hashtags and spaces
    text = _NON_WORD.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


def normalize_term(term: str) -> str:
    """Canonical form for a keyword/hashtag: lowercase, no '#', single spaces."""
    term = (term or "").lower().lstrip("#")
    term = re.sub(r"[^\w\s]", " ", term)
    return _SPACES.sub(" ", term).strip()
