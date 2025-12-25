from dataclasses import dataclass
import os
from dotenv import load_dotenv


@dataclass
class Config:
    bot_token: str
    admin_id: int
    spotify_client_id: str = ""
    spotify_client_secret: str = ""
    api_base_url: str = ""
    api_token: str = ""


def load_config() -> Config:
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "").strip()
    admin_id_str = os.getenv("ADMIN_ID", "").strip()
    spotify_client_id = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
    spotify_client_secret = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()

    api_base_url = (os.getenv("API_BASE_URL") or "").strip()
    if not api_base_url:
        api_base_url = "http://127.0.0.1:8080"
    api_token = (os.getenv("API_TOKEN") or "").strip()

    if not token:
        raise RuntimeError("BOT_TOKEN is not set in environment")
    if not admin_id_str.isdigit():
        raise RuntimeError("ADMIN_ID is not a valid integer in environment")

    return Config(
        bot_token=token,
        admin_id=int(admin_id_str),
        spotify_client_id=spotify_client_id,
        spotify_client_secret=spotify_client_secret,
        api_base_url=api_base_url,
        api_token=api_token,
    )
