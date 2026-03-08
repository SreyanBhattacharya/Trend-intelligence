import pandas as pd
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

def predict_virality(engagement_data: list) -> Dict[str, Any]:
    """
    Predict virality using Prophet from time-series engagement data.
    `engagement_data` is a list of dicts with 'timestamp' and 'total_engagement'.
    """
    if not engagement_data or len(engagement_data) < 3:
        logger.warning("Not enough data to run Prophet, using simple heuristic fallback.")
        return simple_prediction_heuristic(engagement_data)
        
    try:
        from prophet import Prophet
        
        # Prepare dataframe for Prophet
        df = pd.DataFrame(engagement_data)
        df = df.rename(columns={'timestamp': 'ds', 'total_engagement': 'y'})
        df['ds'] = pd.to_datetime(df['ds']).dt.tz_localize(None) # Prophet needs naive datetimes usually
        
        m = Prophet(daily_seasonality=False, weekly_seasonality=False, yearly_seasonality=False)
        m.fit(df)
        
        # Predict next 24 hours (assuming hourly data or similar, we just make a simple future dataframe)
        future = m.make_future_dataframe(periods=24, freq='H')
        forecast = m.predict(future)
        
        # Get the slope/momentum from the trend component roughly
        trend_component = forecast['trend'].values
        momentum = (trend_component[-1] - trend_component[-24]) / (trend_component[-24] + 1)
        
        predicted_max = max(forecast['yhat'].values)
        current_max = max(df['y'].values)
        
        # Calculate a mock virality probability based on momentum and predicted peak vs current
        virality_prob = min(99.0, max(1.0, (predicted_max / (current_max + 1)) * momentum * 100))
        
        return {
            "trend_score": min(100.0, max(0.0, virality_prob * 1.5)), # Scaled up arbitrarily
            "virality_probability": virality_prob,
            "trend_momentum": momentum,
            "estimated_lifespan_days": 3 # Hardcoded placeholder for now
        }
        
    except ImportError:
        logger.warning("Prophet not installed. Falling back to simple heuristic.")
        return simple_prediction_heuristic(engagement_data)
    except Exception as e:
        logger.error(f"Error executing Prophet model: {e}")
        return simple_prediction_heuristic(engagement_data)

def simple_prediction_heuristic(engagement_data: list) -> Dict[str, Any]:
    """Fallback simple heuristic if ML libraries are missing."""
    if not engagement_data:
        return {
            "trend_score": 10.0,
            "virality_probability": 5.0,
            "trend_momentum": 0.0,
            "estimated_lifespan_days": 1
        }
        
    # Get last two points to calculate fake "momentum"
    y1 = engagement_data[0]['total_engagement']
    yn = engagement_data[-1]['total_engagement']
    momentum = (yn - y1) / float(len(engagement_data))
    
    return {
        "trend_score": min(100.0, 50.0 + (momentum * 5)),
        "virality_probability": min(100.0, 30.0 + (momentum * 2)),
        "trend_momentum": float(momentum),
        "estimated_lifespan_days": 2
    }
