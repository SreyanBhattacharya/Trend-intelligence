import os
import logging
from typing import Optional
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql://trend_user:trend_password@localhost:5432/trend_db"
)

# Use connection pooling
try:
    engine = create_engine(
        DATABASE_URL,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base = declarative_base()
except Exception as e:
    logger.error(f"Failed to initialize database connection: {e}")
    engine = None
    SessionLocal = None
    Base = None

def get_db():
    if SessionLocal is None:
        logger.error("Database session factory is not initialized.")
        yield None
        return
        
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
