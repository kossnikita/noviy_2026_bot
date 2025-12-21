from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class _ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- Users ----


class UserOut(_ORM):
    id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_admin: bool
    is_blacklisted: bool
    registered_at: datetime
    last_active: datetime


class UserCreate(BaseModel):
    id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_admin: bool = False
    is_blacklisted: bool = False


class UserUpdate(BaseModel):
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_admin: Optional[bool] = None
    is_blacklisted: Optional[bool] = None


# ---- Chats ----


class ChatOut(_ORM):
    chat_id: int
    type: str
    title: Optional[str] = None
    created_at: datetime


class ChatCreate(BaseModel):
    chat_id: int
    type: str
    title: Optional[str] = None


class ChatUpdate(BaseModel):
    type: Optional[str] = None
    title: Optional[str] = None


# ---- Blacklist ----


class BlacklistOut(_ORM):
    tag: str
    note: Optional[str] = None
    created_at: datetime


class BlacklistCreate(BaseModel):
    tag: str
    note: Optional[str] = None


class BlacklistUpdate(BaseModel):
    note: Optional[str] = None


# ---- Settings ----


class SettingOut(_ORM):
    key: str
    value: Optional[str] = None


class SettingUpsert(BaseModel):
    value: Optional[str] = None


# ---- Spotify tracks ----


class SpotifyTrackOut(_ORM):
    id: int
    spotify_id: str
    name: str
    artist: str
    url: Optional[str] = None
    added_by: int
    added_at: datetime


class SpotifyTrackCreate(BaseModel):
    spotify_id: str
    name: str
    artist: str
    url: Optional[str] = None
    added_by: int


class SpotifyTrackUpdate(BaseModel):
    name: Optional[str] = None
    artist: Optional[str] = None
    url: Optional[str] = None
