from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey
from datetime import datetime
import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://user:password@localhost/ecommerce")

engine = create_async_engine(DATABASE_URL, echo=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    
    id = Column(String, primary_key=True)
    email = Column(String, unique=True, index=True)
    age = Column(Integer)
    gender = Column(String)
    location = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

class Product(Base):
    __tablename__ = "products"
    
    id = Column(String, primary_key=True)
    name = Column(String, index=True)
    description = Column(Text)
    price = Column(Float)
    category_id = Column(String)
    brand = Column(String, index=True)
    stock = Column(Integer, default=0)
    is_available = Column(Boolean, default=True)
    image_url = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

class UserInteraction(Base):
    __tablename__ = "user_interactions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.id"))
    product_id = Column(String, ForeignKey("products.id"))
    interaction_type = Column(String)  # view, cart_add, purchase, rating
    rating = Column(Float, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

class Purchase(Base):
    __tablename__ = "purchases"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.id"))
    product_id = Column(String, ForeignKey("products.id"))
    quantity = Column(Integer, default=1)
    price = Column(Float)
    timestamp = Column(DateTime, default=datetime.utcnow)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session