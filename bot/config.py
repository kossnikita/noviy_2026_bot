from dataclasses import dataclass
import os
from dotenv import load_dotenv


@dataclass
class Config:
    bot_token: str
    admin_id: int
    db_path: str = "database.sqlite3"
    database_url: str = ""
    spotify_client_id: str = ""
    spotify_client_secret: str = ""
    max_tracks_per_user: int = 5


def load_config() -> Config:
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "").strip()
    admin_id_str = os.getenv("ADMIN_ID", "").strip()
    db_path = os.getenv("DB_PATH", "database.sqlite3").strip()
    database_url = os.getenv("DATABASE_URL", "").strip()
    spotify_client_id = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
    spotify_client_secret = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()
    max_tracks_str = os.getenv("MAX_TRACKS_PER_USER", "5").strip()

    if not token:
        raise RuntimeError("BOT_TOKEN is not set in environment")
    if not admin_id_str.isdigit():
        raise RuntimeError("ADMIN_ID is not a valid integer in environment")

    max_tracks = 5
    if max_tracks_str.isdigit():
        max_tracks = int(max_tracks_str)

    return Config(
        bot_token=token,
        admin_id=int(admin_id_str),
        db_path=db_path,
        database_url=database_url,
        spotify_client_id=spotify_client_id,
        spotify_client_secret=spotify_client_secret,
        max_tracks_per_user=max_tracks,
    )
