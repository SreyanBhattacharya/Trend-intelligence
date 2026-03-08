import re

def clean_text(text: str) -> str:
    """Clean and normalize social media text for NLP processing."""
    if not text:
        return ""
        
    text = text.lower()
    
    # Remove URLs
    text = re.sub(r'http\S+|www\.\S+', '', text)
    
    # Remove mentions
    text = re.sub(r'@\w+', '', text)
    
    # Remove special characters except alphanumeric, hashtags and spaces
    text = re.sub(r'[^\w\s#]', '', text)
    
    # Replace multiple spaces with single space
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text
