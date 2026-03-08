import logging

logger = logging.getLogger(__name__)

def detect_spikes(keywords_data: list) -> list:
    """
    Detect spikes in keyword frequency.
    In a real implementation, this would compare current frequency vs historical baseline (Z-score, IQR, etc.)
    For this mocked version, we'll just return the top keywords with high frequency.
    """
    spikes = []
    for kw in keywords_data:
        # Mock logic: if we see a keyword more than X times, call it a spike
        if kw['frequency'] > 10: 
            spikes.append(kw)
    return spikes

def cluster_topics(posts_data: list) -> list:
    """
    Cluster posts using BERTopic or similar.
    Since BERTopic can take time to load and run, we will mock the clustering
    if the list is small, or use a simplified sklearn approach.
    """
    if not posts_data:
        return []
        
    logger.info(f"Running topic clustering on {len(posts_data)} posts...")
    
    # We will safely import sklearn/bertopic inside the function to avoid overhead
    # if the agent isn't calling this.
    try:
        from bertopic import BERTopic
        
        docs = [f"{p['title']} {p['body']}" for p in posts_data if p['title'] or p['body']]
        
        if len(docs) < 10:
            logger.info("Not enough docs for BERTopic, returning empty clusters.")
            return []
            
        topic_model = BERTopic(language="english", calculate_probabilities=False, verbose=False)
        topics, probs = topic_model.fit_transform(docs)
        
        topic_info = topic_model.get_topic_info()
        
        clusters = []
        for index, row in topic_info.iterrows():
            if row['Topic'] == -1: 
                continue # Ignore outlier topic
                
            # Get the top keywords for the topic representation
            top_words = [word[0] for word in topic_model.get_topic(row['Topic'])][:3]
            topic_name = " ".join(top_words)
            
            clusters.append({
                "topic_id": row['Topic'],
                "topic_name": topic_name,
                "size": row['Count']
            })
            
        return clusters
    except ImportError:
        logger.warning("BERTopic not installed or failed to import. Skipping actual clustering.")
        return []
    except Exception as e:
        logger.error(f"Error in topic clustering: {e}")
        return []
