import spacy
import logging
from typing import List

logger = logging.getLogger(__name__)

# Load spacy model lazily
_nlp = None

def get_nlp():
    global _nlp
    if _nlp is None:
        try:
            _nlp = spacy.load("en_core_web_sm")
        except OSError:
            logger.warning("spacy model 'en_core_web_sm' not found. Keywords extraction might be degraded. Did you run 'python -m spacy download en_core_web_sm'?")
            # We can return a dummy or download it here dynamically if needed, 
            # but usually it's better to just let it fail or downgrade gracefully.
            return None
    return _nlp

def extract_keywords(text: str) -> List[str]:
    """Extract relevant keywords (Nouns, PROPN) using spaCy."""
    if not text:
        return []
        
    nlp = get_nlp()
    if not nlp:
        # Fallback to simple split if Spacy isn't loaded
        words = text.split()
        return [w for w in words if len(w) > 4]
        
    doc = nlp(text)
    keywords = []
    
    # Keep proper nouns and common nouns, ignore stop words
    for token in doc:
        if token.pos_ in ['NOUN', 'PROPN', 'ADJ'] and not token.is_stop and len(token.text) > 3:
            keywords.append(token.text.lower())
            
    return list(set(keywords))
