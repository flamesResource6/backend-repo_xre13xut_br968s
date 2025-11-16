"""
Database Schemas for ShootUp

Each Pydantic model represents a collection in MongoDB. The collection name
is the lowercase of the class name.
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class Userprofile(BaseModel):
    """
    User profile collection (collection name: "userprofile")
    """
    user_id: str = Field(..., description="App-scoped user identifier")
    username: str = Field(..., description="Display name")
    avatar_url: Optional[str] = Field(None, description="Profile photo URL")
    bio: Optional[str] = None
    following_events: List[str] = Field(default_factory=list, description="Event IDs followed")

class Event(BaseModel):
    """
    Event collection (collection name: "event")
    """
    code: str = Field(..., description="Human-friendly join code encoded in QR")
    title: str
    date_iso: Optional[str] = Field(None, description="ISO date string of event start")
    location: Optional[str] = None
    access: str = Field("public", description="public|private")
    cover_url: Optional[str] = None
    participants: List[str] = Field(default_factory=list, description="User IDs of participants")
    challenges: List[str] = Field(default_factory=list, description="Simple challenge prompts")
    ended: bool = False

class Media(BaseModel):
    """
    Media uploaded by participants (collection name: "media")
    """
    event_id: str = Field(..., description="Event ObjectId as string")
    user_id: str
    url: str = Field(..., description="Photo/video URL")
    media_type: str = Field("photo", description="photo|video")
    challenge: Optional[str] = Field(None, description="Prompt text if tied to a challenge")
    likes_count: int = 0
    comments_count: int = 0

class Comment(BaseModel):
    """
    Comments on media (collection name: "comment")
    """
    media_id: str
    user_id: str
    text: str

class Like(BaseModel):
    """
    Likes on media (collection name: "like")
    """
    media_id: str
    user_id: str

# Minimal schema used when creating via database helper
class SimpleDoc(BaseModel):
    key: str
    value: str
