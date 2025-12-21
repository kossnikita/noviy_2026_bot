"""Database layer (SQLAlchemy + Alembic) for the API service."""

from api.db_migrations import upgrade_head
from api.db_sa import Db, create_db
from api.db_sa import BlacklistRepo as _BlacklistRepo
from api.db_sa import ChatRepo as _ChatRepo
from api.db_sa import SettingsRepo as _SettingsRepo
from api.db_sa import SpotifyTracksRepo as _SpotifyTracksRepo
from api.db_sa import UserRepo as _UserRepo

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
    db = create_db(database_url=database_url, db_path=db_path)
    upgrade_head()
    return db
