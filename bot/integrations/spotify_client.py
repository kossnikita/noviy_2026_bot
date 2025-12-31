import base64
import logging
import time
from dataclasses import dataclass
from typing import Optional

import requests


@dataclass(frozen=True)
class SpotifyTrack:
    spotify_id: str
    name: str
    artist: str
    url: Optional[str]
    duration_ms: int = 0


class SpotifyClient:
    """Minimal Spotify Web API client (Client Credentials flow)."""

    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self._log = logging.getLogger(self.__class__.__name__)
        self._token: Optional[str] = None
        self._token_exp: float = 0.0

    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def _get_token(self) -> str:
        now = time.time()
        if self._token and now < self._token_exp - 30:
            return self._token

        auth_raw = f"{self.client_id}:{self.client_secret}".encode("utf-8")
        auth = base64.b64encode(auth_raw).decode("ascii")
        resp = requests.post(
            "https://accounts.spotify.com/api/token",
            headers={"Authorization": f"Basic {auth}"},
            data={"grant_type": "client_credentials"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._token_exp = now + float(data.get("expires_in", 3600))
        self._log.debug("Spotify token refreshed")
        return self._token

    def _headers(self) -> dict:
        token = self._get_token()
        return {"Authorization": f"Bearer {token}"}

    @staticmethod
    def parse_spotify_track_id(text: str) -> Optional[str]:
        if not text:
            return None
        t = text.strip()
        # URL: https://open.spotify.com/track/<id>?...
        if "open.spotify.com/track/" in t:
            try:
                part = t.split("open.spotify.com/track/", 1)[1]
                track_id = part.split("?", 1)[0].split("/", 1)[0]
                return track_id or None
            except Exception:
                return None
        # URI: spotify:track:<id>
        if t.startswith("spotify:track:"):
            track_id = t.split(":")[-1]
            return track_id or None
        return None

    def get_track(self, spotify_id: str) -> SpotifyTrack:
        resp = requests.get(
            f"https://api.spotify.com/v1/tracks/{spotify_id}",
            headers=self._headers(),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        name = data.get("name") or ""
        artists = data.get("artists") or []
        artist = (artists[0].get("name") if artists else "") or ""
        url = None
        ext = data.get("external_urls") or {}
        if isinstance(ext, dict):
            url = ext.get("spotify")
        return SpotifyTrack(
            spotify_id=spotify_id, name=name, artist=artist, url=url
        )

    def search_track(self, query: str) -> Optional[SpotifyTrack]:
        q = (query or "").strip()
        if not q:
            return None
        resp = requests.get(
            "https://api.spotify.com/v1/search",
            headers=self._headers(),
            params={"type": "track", "limit": 1, "q": q},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        tracks = ((data.get("tracks") or {}).get("items")) or []
        if not tracks:
            return None
        t0 = tracks[0]
        spotify_id = t0.get("id")
        name = t0.get("name") or ""
        artists = t0.get("artists") or []
        artist = (artists[0].get("name") if artists else "") or ""
        url = None
        ext = t0.get("external_urls") or {}
        if isinstance(ext, dict):
            url = ext.get("spotify")
        if not spotify_id:
            return None
        return SpotifyTrack(
            spotify_id=spotify_id, name=name, artist=artist, url=url
        )
