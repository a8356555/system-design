from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, String, Integer, Float, DateTime, Boolean, Text, ForeignKey, JSON
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import os

Base = declarative_base()

class UserModel(Base):
    __tablename__ = "users"
    
    id = Column(String, primary_key=True)
    email = Column(String, unique=True, index=True)
    subscription_tier = Column(String, default="free")
    country = Column(String)
    timezone = Column(String)
    preferred_device = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_active = Column(DateTime, default=datetime.utcnow)
    
    profiles = relationship("UserProfileModel", back_populates="user")
    interactions = relationship("UserInteractionModel", back_populates="user")

class UserProfileModel(Base):
    __tablename__ = "user_profiles"
    
    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"))
    name = Column(String, nullable=False)
    age = Column(Integer)
    preferred_genres = Column(JSON)  # Store as JSON array
    preferred_languages = Column(JSON)  # Store as JSON array
    is_kids_profile = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("UserModel", back_populates="profiles")

class ContentModel(Base):
    __tablename__ = "content"
    
    id = Column(String, primary_key=True)
    title = Column(String, nullable=False, index=True)
    content_type = Column(String, nullable=False, index=True)
    duration_minutes = Column(Integer)
    release_date = Column(DateTime)
    genres = Column(JSON)  # Store as JSON array
    rating = Column(String)  # Content rating (PG, R, etc.)
    description = Column(Text)
    cast = Column(JSON)  # Store as JSON array
    directors = Column(JSON)  # Store as JSON array
    language = Column(String, index=True)
    country = Column(String)
    imdb_rating = Column(Float)
    poster_url = Column(String)
    trailer_url = Column(String)
    series_id = Column(String, index=True)  # For episodes
    season_number = Column(Integer)
    episode_number = Column(Integer)
    is_premium = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

class UserInteractionModel(Base):
    __tablename__ = "user_interactions"
    
    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), index=True)
    profile_id = Column(String, ForeignKey("user_profiles.id"), index=True)
    content_id = Column(String, ForeignKey("content.id"), index=True)
    interaction_type = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    session_id = Column(String, index=True)
    device_type = Column(String)
    progress_seconds = Column(Integer)
    rating = Column(Float)
    duration_watched_seconds = Column(Integer)
    metadata = Column(JSON)
    
    user = relationship("UserModel", back_populates="interactions")

class ViewingProgressModel(Base):
    __tablename__ = "viewing_progress"
    
    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), index=True)
    profile_id = Column(String, ForeignKey("user_profiles.id"), index=True)
    content_id = Column(String, ForeignKey("content.id"), index=True)
    progress_seconds = Column(Integer, default=0)
    total_duration_seconds = Column(Integer)
    last_watched = Column(DateTime, default=datetime.utcnow)
    is_completed = Column(Boolean, default=False)
    watch_count = Column(Integer, default=1)

class ContentRatingModel(Base):
    __tablename__ = "content_ratings"
    
    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), index=True)
    profile_id = Column(String, ForeignKey("user_profiles.id"), index=True)
    content_id = Column(String, ForeignKey("content.id"), index=True)
    rating = Column(Float, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    review_text = Column(Text)

class ViewingSessionModel(Base):
    __tablename__ = "viewing_sessions"
    
    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), index=True)
    profile_id = Column(String, ForeignKey("user_profiles.id"), index=True)
    device_type = Column(String)
    start_time = Column(DateTime, default=datetime.utcnow)
    end_time = Column(DateTime)
    location = Column(String)

# Database connection setup
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:password@localhost/streaming")

engine = create_async_engine(DATABASE_URL, echo=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session