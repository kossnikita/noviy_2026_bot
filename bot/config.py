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
    api_token = (os.getenv("BOT_API_TOKEN") or "").strip()

    # For tests and local dev, allow missing BOT_TOKEN and ADMIN_ID by providing
    # sensible defaults. Callers that need a real bot token should validate it.
    if not token:
        token = ""
    if not admin_id_str.isdigit():
        # Default admin id to 0 when not provided or invalid.
        admin_id_str = "0"

    return Config(
        bot_token=token,
        admin_id=int(admin_id_str),
        spotify_client_id=spotify_client_id,
        spotify_client_secret=spotify_client_secret,
        api_base_url=api_base_url,
        api_token=api_token,
    )
