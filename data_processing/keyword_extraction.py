"""Keyword and key-phrase extraction.

Terms are:

* single words that spaCy tags as nouns / proper nouns / adjectives, and
* 2-3 word n-grams taken from runs of consecutive non-stop-words
  ("everyone is trying ai voice clones right now" -> "ai voice", "voice clones",
  "ai voice clones", ...).

N-grams are used instead of spaCy noun chunks because the small spaCy model
parses lowercase social-media text inconsistently ("ai" is often tagged as a
verb), which would split one trend across several phrases. The detector later
picks the most specific phrase that carries most of a spike's volume.

Without spaCy (or its model) a stop-word list replaces the POS filter, so the
pipeline still runs.
"""
import logging
import re
from typing import List

from data_processing.cleaning_pipeline import normalize_term

logger = logging.getLogger(__name__)

_nlp = None
_nlp_failed = False

MIN_LEN = 3
MAX_LEN = 50

FALLBACK_STOPWORDS = set("""
a about above after again against all also am an and any are aren as at be because been before being below
between both but by can could did do does doing don down during each few for from further get got had has
have having he her here hers herself him himself his how i if in into is it its itself just know like ll
me more most my myself new no nor not now of off on once one only or other our ours ourselves out over own
people really same she should so some such than that the their theirs them themselves then there these
they this those through to too under until up us very was we were what when where which while who whom
why will with would you your yours yourself yourselves amp via today time way make made want need going
""".split())


def get_nlp():
    global _nlp, _nlp_failed
    if _nlp is None and not _nlp_failed:
        try:
            import spacy

            _nlp = spacy.load("en_core_web_sm", disable=["ner", "lemmatizer"])
        except Exception as e:  # ImportError or OSError (model missing)
            _nlp_failed = True
            logger.warning(
                "spaCy model 'en_core_web_sm' unavailable (%s); using fallback keyword extraction. "
                "Run 'python -m spacy download en_core_web_sm' for better results.", e)
    return _nlp


def _valid(term: str) -> bool:
    if not (MIN_LEN <= len(term) <= MAX_LEN):
        return False
    if term.isdigit():
        return False
    return True


def _stopwords():
    nlp = get_nlp()
    if nlp is not None:
        return nlp.Defaults.stop_words | FALLBACK_STOPWORDS
    return FALLBACK_STOPWORDS


def _ngrams(tokens: List[str], stop: set) -> List[str]:
    """2-3 grams inside runs of consecutive non-stop-word tokens."""
    terms, run = [], []
    for tok in tokens + [None]:  # sentinel flushes the last run
        if tok is None or tok in stop or tok.isdigit() or not re.match(r"^[a-z0-9_]+$", tok):
            for n in (2, 3):
                terms.extend(" ".join(run[i:i + n]) for i in range(len(run) - n + 1))
            run = []
        else:
            run.append(tok)
    return terms


def _fallback(text: str) -> List[str]:
    tokens = re.findall(r"[a-z0-9_]+", text.lower())
    terms = {t for t in tokens if t not in FALLBACK_STOPWORDS and len(t) > 3 and not t.isdigit()}
    terms.update(_ngrams(tokens, FALLBACK_STOPWORDS))
    return sorted(t for t in terms if _valid(t))


def extract_keywords(text: str) -> List[str]:
    """Return a de-duplicated list of normalized keywords and key phrases."""
    if not text:
        return []

    nlp = get_nlp()
    if not nlp:
        return _fallback(text)

    doc = nlp(text)
    stop = _stopwords()
    terms = {
        normalize_term(t.text) for t in doc
        if t.pos_ in ("NOUN", "PROPN", "ADJ") and not t.is_stop and len(t.text) > 3
    }
    tokens = [normalize_term(t.text) for t in doc if not t.is_punct and not t.is_space and t.text != "#"]
    terms.update(_ngrams([t for t in tokens if t], stop))
    return sorted(t for t in terms if _valid(t))
