import os
import logging
import sys
from pathlib import Path

# Add the root directory to the Python path
sys.path.append(str(Path(__file__).parent.resolve()))

from database.db_connection import engine, Base

def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    logger = logging.getLogger(__name__)
    
    logger.info("Starting Trend Intelligence Platform...")
    
    # Ensure database tables exist (if we were using SQLAlchemy to create them)
    # Since we are using schema.sql in docker-compose, this is mostly checking connection
    try:
        if engine is not None:
            connection = engine.connect()
            logger.info("Successfully connected to the PostgreSQL database.")
            connection.close()
        else:
            logger.warning("Database engine is not initialized. Skipping connection check.")
    except Exception as e:
        logger.error(f"Failed to connect to the database: {e}. Continuing anyway.")

    logger.info("Application started. Waiting for celery worker/beat processes to handle actual workloads via Docker Compose.")
    
    # In a local non-docker run, we might start APScheduler here instead.
    # We will block here to keep the main container alive if run directly.
    import time
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("Shutting down...")

if __name__ == "__main__":
    main()
