import logging
from sqlalchemy import text
from database.db_connection import engine
from ai_models.prediction_model import predict_virality

logger = logging.getLogger(__name__)

class PredictionAgent:
    """Agent that scores identified trends and predicts virality probability."""
    
    def predict_trends(self):
        if not engine:
            return
            
        logger.info("Starting prediction agent run.")
        
        # Fetch active trends
        active_trends_query = text("SELECT id, trend_name FROM trends WHERE is_active = TRUE")
        
        # Mock engagement time series generation
        # In a real app we'd have a time-series table tracking the trend's engagement over time
        # Here we mock it by generating linear/exponential growth based on random values or post scores
        
        try:
            with engine.connect() as conn:
                trends = conn.execute(active_trends_query).mappings().fetchall()
                
                if not trends:
                    logger.info("No active trends to predict.")
                    return
                
                with conn.begin():
                    for trend in trends:
                        # Generating dummy engagement data for the trend to feed Prophet
                        # E.g., looking at `engagement_metrics` table
                        metrics_query = text("""
                            SELECT timestamp, total_engagement 
                            FROM engagement_metrics 
                            WHERE trend_id = :trend_id 
                            ORDER BY timestamp ASC
                        """)
                        metrics = conn.execute(metrics_query, {"trend_id": trend['id']}).mappings().fetchall()
                        
                        # Fallback dummy data if no metrics recorded yet
                        if len(metrics) < 3:
                            import datetime
                            import random
                            base = datetime.datetime.now()
                            # Create 5 synthetic data points to bootstrap
                            metrics = [
                                {"timestamp": base - datetime.timedelta(hours=5-i), 
                                 "total_engagement": random.randint(100, 500) * (i+1)}
                                for i in range(5)
                            ]
                        
                        # Predict
                        result = predict_virality(list(metrics))
                        
                        # Update database
                        insert_pred_query = text("""
                            INSERT INTO trend_predictions (
                                trend_id, predicted_at, trend_score, virality_probability, 
                                trend_momentum, estimated_lifespan_days
                            ) VALUES (
                                :trend_id, CURRENT_TIMESTAMP, :score, :prob, :mom, :life
                            )
                        """)
                        conn.execute(insert_pred_query, {
                            "trend_id": trend['id'],
                            "score": result['trend_score'],
                            "prob": result['virality_probability'],
                            "mom": result['trend_momentum'],
                            "life": result['estimated_lifespan_days']
                        })
                        
                        logger.info(f"Trend '{trend['trend_name']}' scored: {result['trend_score']:.2f} (Virality: {result['virality_probability']:.2f}%)")
                        
                logger.info("Prediction run complete.")
        except Exception as e:
            logger.error(f"Error in prediction agent: {e}")
