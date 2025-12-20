"""Database layer (SQLAlchemy + Alembic).

This module intentionally preserves the old import surface (e.g. `from bot.db import UserRepo`).
"""

from bot.db_sa import Db, create_db
from bot.db_sa import UserRepo as _UserRepo
from bot.db_sa import ChatRepo as _ChatRepo
from bot.db_sa import BlacklistRepo as _BlacklistRepo
from bot.db_sa import SettingsRepo as _SettingsRepo
from bot.db_sa import SpotifyTracksRepo as _SpotifyTracksRepo
from bot.db_migrations import upgrade_head

UserRepo = _UserRepo
ChatRepo = _ChatRepo
BlacklistRepo = _BlacklistRepo
SettingsRepo = _SettingsRepo
SpotifyTracksRepo = _SpotifyTracksRepo

__all__ = [
    "Db",
    "create_db",
    "init_db",
    "UserRepo",
    "ChatRepo",
    "BlacklistRepo",
    "SettingsRepo",
    "SpotifyTracksRepo",
]


def init_db(*, database_url: str, db_path: str) -> Db:
    """Create engine/session factory and apply Alembic migrations."""
    db = create_db(database_url=database_url, db_path=db_path)
    upgrade_head()
    return db

