"""
Response models for the Serving Layer API
"""

from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


class UserPostCountData(BaseModel):
    """Internal model for user post count data"""
    user_id: int
    post_count: int
    last_updated: datetime


class UserPostCount(BaseModel):
    """Response model for user post count queries"""
    user_id: int = Field(..., description="User ID", ge=1)
    post_count: int = Field(..., description="Total post count", ge=0)
    last_updated: datetime = Field(..., description="Last update timestamp")
    batch_count: Optional[int] = Field(None, description="Count from batch layer")
    speed_count: Optional[int] = Field(None, description="Count from speed layer")
    data_source: str = Field(default="lambda", description="Data source indicator")
    
    class Config:
        schema_extra = {
            "example": {
                "user_id": 12345,
                "post_count": 142,
                "last_updated": "2024-01-15T10:30:00Z",
                "batch_count": 140,
                "speed_count": 2,
                "data_source": "lambda"
            }
        }


class TopUsersResponse(BaseModel):
    """Response model for top users query"""
    users: List[UserPostCount] = Field(..., description="List of top users")
    total_users: int = Field(..., description="Total number of users returned")
    last_updated: datetime = Field(..., description="Response generation timestamp")
    data_freshness_seconds: Optional[int] = Field(None, description="Data freshness in seconds")
    
    class Config:
        schema_extra = {
            "example": {
                "users": [
                    {
                        "user_id": 12345,
                        "post_count": 500,
                        "last_updated": "2024-01-15T10:30:00Z",
                        "data_source": "lambda"
                    }
                ],
                "total_users": 100,
                "last_updated": "2024-01-15T11:00:00Z",
                "data_freshness_seconds": 3600
            }
        }


class SystemHealthResponse(BaseModel):
    """Response model for system health query"""
    total_users: int = Field(default=0, description="Total number of users")
    total_posts: int = Field(default=0, description="Total number of posts")
    active_boards: int = Field(default=0, description="Number of active boards")
    batch_cutoff_time: Optional[datetime] = Field(None, description="Batch processing cutoff time")
    data_freshness_seconds: Optional[int] = Field(None, description="Data freshness in seconds")
    speed_layer_health: str = Field(default="unknown", description="Speed layer health status")
    batch_layer_health: str = Field(default="unknown", description="Batch layer health status")
    last_updated: datetime = Field(..., description="Response generation timestamp")
    
    class Config:
        schema_extra = {
            "example": {
                "total_users": 1000000,
                "total_posts": 5000000,
                "active_boards": 50,
                "batch_cutoff_time": "2024-01-15T00:00:00Z",
                "data_freshness_seconds": 3600,
                "speed_layer_health": "healthy",
                "batch_layer_health": "healthy",
                "last_updated": "2024-01-15T11:00:00Z"
            }
        }


class DataFreshnessResponse(BaseModel):
    """Response model for data freshness information"""
    batch_cutoff_time: datetime = Field(..., description="Batch processing cutoff time")
    data_freshness_seconds: int = Field(..., description="Data freshness in seconds")
    is_healthy: bool = Field(..., description="Whether data freshness is healthy")
    last_batch_run: Optional[datetime] = Field(None, description="Last batch run completion time")
    speed_layer_delay_seconds: Optional[int] = Field(None, description="Speed layer processing delay")
    
    class Config:
        schema_extra = {
            "example": {
                "batch_cutoff_time": "2024-01-15T00:00:00Z",
                "data_freshness_seconds": 3600,
                "is_healthy": True,
                "last_batch_run": "2024-01-15T02:30:00Z",
                "speed_layer_delay_seconds": 30
            }
        }


class ErrorResponse(BaseModel):
    """Response model for error cases"""
    detail: str = Field(..., description="Error message")
    timestamp: datetime = Field(..., description="Error timestamp")
    
    class Config:
        schema_extra = {
            "example": {
                "detail": "User not found",
                "timestamp": "2024-01-15T11:00:00Z"
            }
        }