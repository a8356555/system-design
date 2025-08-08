from abc import ABC, abstractmethod
from typing import List, Optional
from ..entities.user import User, UserProfile

class UserRepositoryInterface(ABC):
    
    @abstractmethod
    async def get_by_id(self, user_id: str) -> Optional[User]:
        """Get user by ID"""
        pass
    
    @abstractmethod
    async def get_profile_by_id(self, profile_id: str) -> Optional[UserProfile]:
        """Get user profile by ID"""
        pass
    
    @abstractmethod
    async def get_user_profiles(self, user_id: str) -> List[UserProfile]:
        """Get all profiles for a user"""
        pass
    
    @abstractmethod
    async def create_user(self, user: User) -> User:
        """Create a new user"""
        pass
    
    @abstractmethod
    async def update_user(self, user: User) -> User:
        """Update user information"""
        pass
    
    @abstractmethod
    async def create_profile(self, user_id: str, profile: UserProfile) -> UserProfile:
        """Create a new user profile"""
        pass
    
    @abstractmethod
    async def update_profile(self, profile: UserProfile) -> UserProfile:
        """Update user profile"""
        pass
    
    @abstractmethod
    async def delete_profile(self, profile_id: str) -> bool:
        """Delete a user profile"""
        pass