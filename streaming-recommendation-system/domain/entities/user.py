from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime
from enum import Enum

class SubscriptionTier(Enum):
    FREE = "free"
    BASIC = "basic"
    PREMIUM = "premium"
    FAMILY = "family"

class DeviceType(Enum):
    TV = "tv"
    MOBILE = "mobile"
    TABLET = "tablet"
    DESKTOP = "desktop"
    LAPTOP = "laptop"

@dataclass
class UserProfile:
    id: str
    name: str
    age: Optional[int] = None
    preferred_genres: List[str] = field(default_factory=list)
    preferred_languages: List[str] = field(default_factory=list)
    is_kids_profile: bool = False
    created_at: datetime = field(default_factory=datetime.utcnow)

    def can_watch_content(self, content_rating: str) -> bool:
        if self.is_kids_profile:
            kids_allowed = ["G", "PG", "TV-Y", "TV-PG"]
            return content_rating in kids_allowed
        
        if self.age and self.age < 18:
            teen_restricted = ["R", "NC-17", "TV-MA"]
            return content_rating not in teen_restricted
            
        return True

@dataclass
class User:
    id: str
    email: str
    subscription_tier: SubscriptionTier
    country: str
    timezone: str
    profiles: List[UserProfile] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_active: datetime = field(default_factory=datetime.utcnow)
    preferred_device: Optional[DeviceType] = None

    def has_premium_access(self) -> bool:
        return self.subscription_tier in [SubscriptionTier.PREMIUM, SubscriptionTier.FAMILY]

    def can_create_profiles(self) -> bool:
        return self.subscription_tier in [SubscriptionTier.PREMIUM, SubscriptionTier.FAMILY]

    def get_profile_by_id(self, profile_id: str) -> Optional[UserProfile]:
        return next((p for p in self.profiles if p.id == profile_id), None)

    def add_profile(self, profile: UserProfile) -> bool:
        if not self.can_create_profiles() and len(self.profiles) >= 1:
            return False
        
        max_profiles = 6 if self.subscription_tier == SubscriptionTier.FAMILY else 4
        if len(self.profiles) >= max_profiles:
            return False
            
        self.profiles.append(profile)
        return True

@dataclass
class ViewingSession:
    id: str
    user_id: str
    profile_id: str
    device_type: DeviceType
    start_time: datetime
    end_time: Optional[datetime] = None
    location: Optional[str] = None  # IP-based location

    def get_duration_minutes(self) -> int:
        if self.end_time:
            return int((self.end_time - self.start_time).total_seconds() / 60)
        return 0

    def is_active(self) -> bool:
        return self.end_time is None