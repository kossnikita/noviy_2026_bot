from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Optional

import requests


class ApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class ApiSettings:
    base_url: str
    timeout_s: float = 5.0
    token: Optional[str] = None


class _Api:
    def __init__(self, settings: ApiSettings):
        self.settings = settings
        self._session = requests.Session()
        self._log = logging.getLogger("bot.api")

        if settings.token:
            self._session.headers.update(
                {"Authorization": f"Bearer {settings.token.strip()}"}
            )

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return self.settings.base_url.rstrip("/") + path

    def _request(self, method: str, path: str, *, json: object | None = None):
        url = self._url(path)
        try:
            resp = self._session.request(
                method,
                url,
                json=json,
                timeout=self.settings.timeout_s,
            )
        except Exception as e:
            raise ApiError(f"API request failed: {method} {url}: {e}") from e
        return resp

    def get_json(self, path: str):
        resp = self._request("GET", path)
        if resp.status_code >= 400:
            raise ApiError(
                f"API GET {path} failed: {resp.status_code} {resp.text}"
            )
        return resp.json()

    def post_json(self, path: str, payload: object):
        resp = self._request("POST", path, json=payload)
        return resp

    def put_json(self, path: str, payload: object):
        resp = self._request("PUT", path, json=payload)
        return resp

    def delete(self, path: str):
        resp = self._request("DELETE", path)
        return resp


class UserRepo:
    def __init__(self, api: _Api):
        self._api = api

    def exists(self, user_id: int) -> bool:
        resp = self._api._request("GET", f"/users/{user_id}")
        if resp.status_code == 404:
            return False
        if resp.status_code >= 400:
            raise ApiError(
                f"API users/{user_id} failed: {resp.status_code} {resp.text}"
            )
        return True

    def upsert_user(
        self,
        user_id: int,
        username: Optional[str],
        first: Optional[str],
        last: Optional[str],
        is_admin: bool,
        is_blacklisted: bool = False,
    ) -> None:
        if not self.exists(user_id):
            resp = self._api.post_json(
                "/users",
                {
                    "id": int(user_id),
                    "username": username,
                    "first_name": first,
                    "last_name": last,
                    "is_admin": bool(is_admin),
                    "is_blacklisted": bool(is_blacklisted),
                },
            )
            if resp.status_code == 201:
                return
            if resp.status_code != 409:
                raise ApiError(
                    f"API create user failed: {resp.status_code} {resp.text}"
                )

        resp = self._api.put_json(
            f"/users/{user_id}",
            {
                "username": username,
                "first_name": first,
                "last_name": last,
                "is_admin": bool(is_admin),
                "is_blacklisted": bool(is_blacklisted),
            },
        )
        if resp.status_code >= 400:
            raise ApiError(
                f"API update user failed: {resp.status_code} {resp.text}"
            )

    def touch_activity(self, user_id: int) -> None:
        # API updates last_active on any PUT.
        resp = self._api.put_json(f"/users/{user_id}", {})
        if resp.status_code == 404:
            return
        if resp.status_code >= 400:
            raise ApiError(f"API touch failed: {resp.status_code} {resp.text}")

    def blacklist_by_username(self, username: str) -> int:
        resp = self._api.post_json(
            "/users/blacklist-by-username",
            {"username": username},
        )
        if resp.status_code >= 400:
            raise ApiError(
                f"API blacklist-by-username failed: {resp.status_code} {resp.text}"
            )
        data = resp.json() if resp.content else {}
        return int((data or {}).get("updated") or 0)

    def count(self) -> int:
        data = self._api.get_json("/users?limit=100000&offset=0")
        return len(list(data or []))


class ChatRepo:
    def __init__(self, api: _Api):
        self._api = api

    def upsert_chat(
        self, chat_id: int, chat_type: str, title: Optional[str]
    ) -> None:
        resp = self._api._request("GET", f"/chats/{chat_id}")
        if resp.status_code == 404:
            r2 = self._api.post_json(
                "/chats",
                {"chat_id": int(chat_id), "type": chat_type, "title": title},
            )
            if r2.status_code in {200, 201}:
                return
            if r2.status_code != 409:
                raise ApiError(
                    f"API create chat failed: {r2.status_code} {r2.text}"
                )
        elif resp.status_code >= 400:
            raise ApiError(
                f"API get chat failed: {resp.status_code} {resp.text}"
            )

        r3 = self._api.put_json(
            f"/chats/{chat_id}",
            {"type": chat_type, "title": title},
        )
        if r3.status_code >= 400:
            raise ApiError(
                f"API update chat failed: {r3.status_code} {r3.text}"
            )

    def count(self) -> int:
        resp = self._api._request("GET", "/chats/group-count")
        if resp.status_code >= 400:
            raise ApiError(
                f"API group-count failed: {resp.status_code} {resp.text}"
            )
        return int((resp.json() or {}).get("count") or 0)

    def group_chat_ids(self) -> Iterable[int]:
        resp = self._api._request("GET", "/chats/group-ids")
        if resp.status_code >= 400:
            raise ApiError(
                f"API group-ids failed: {resp.status_code} {resp.text}"
            )
        for cid in resp.json() or []:
            yield int(cid)


class BlacklistRepo:
    def __init__(self, api: _Api):
        self._api = api

    def add(self, tag: str, note: Optional[str] = None) -> None:
        r = self._api.post_json("/blacklist", {"tag": tag, "note": note})
        if r.status_code == 201:
            return
        if r.status_code == 409:
            key = tag.lstrip("@").lower()
            r2 = self._api.put_json(f"/blacklist/{key}", {"note": note})
            if r2.status_code >= 400:
                raise ApiError(
                    f"API blacklist update failed: {r2.status_code} {r2.text}"
                )
            return
        raise ApiError(
            f"API blacklist create failed: {r.status_code} {r.text}"
        )

    def remove(self, tag: str) -> None:
        key = tag.lstrip("@").lower()
        r = self._api.delete(f"/blacklist/{key}")
        if r.status_code in {204, 404}:
            return
        if r.status_code >= 400:
            raise ApiError(
                f"API blacklist delete failed: {r.status_code} {r.text}"
            )

    def list(self) -> Iterable[tuple]:
        items = self._api.get_json("/blacklist?limit=1000&offset=0")
        for it in items or []:
            yield (it.get("tag"), it.get("note"), it.get("created_at"))

    def matches(self, username: Optional[str]) -> bool:
        if not username:
            return False
        key = username.lstrip("@").lower()
        r = self._api._request("GET", f"/blacklist/{key}")
        if r.status_code == 404:
            return False
        if r.status_code >= 400:
            raise ApiError(
                f"API blacklist get failed: {r.status_code} {r.text}"
            )
        return True


class SettingsRepo:
    def __init__(self, api: _Api):
        self._api = api

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        r = self._api._request("GET", f"/settings/{key}")
        if r.status_code == 404:
            return default
        if r.status_code >= 400:
            raise ApiError(f"API setting get failed: {r.status_code} {r.text}")
        data = r.json() or {}
        val = data.get("value")
        return val if val is not None else default

    def set(self, key: str, value: str) -> None:
        r = self._api.put_json(f"/settings/{key}", {"value": value})
        if r.status_code >= 400:
            raise ApiError(f"API setting set failed: {r.status_code} {r.text}")


class PhotosRepo:
    def __init__(self, api: _Api):
        self._api = api

    def create(self, *, name: str, url: str, added_by: int) -> dict:
        r = self._api.post_json(
            "/photos",
            {"name": str(name), "url": str(url), "added_by": int(added_by)},
        )
        if r.status_code >= 400:
            raise ApiError(
                f"API create photo failed: {r.status_code} {r.text}"
            )
        return r.json() if r.content else {}

    def upload(self, *, file_path: str, filename: str, added_by: int) -> dict:
        url = self._api._url("/photos/upload")
        try:
            with open(file_path, "rb") as f:
                resp = self._api._session.request(
                    "POST",
                    url,
                    data={"added_by": str(int(added_by))},
                    files={
                        "file": (str(filename), f, "application/octet-stream")
                    },
                    timeout=self._api.settings.timeout_s,
                )
        except Exception as e:
            raise ApiError(f"API upload photo failed: POST {url}: {e}") from e

        if resp.status_code >= 400:
            raise ApiError(
                f"API upload photo failed: {resp.status_code} {resp.text}"
            )
        return resp.json() if resp.content else {}


class SpotifyTracksRepo:
    def __init__(self, api: _Api):
        self._api = api

    def list_all(self, limit: int = 10000):
        """Get all tracks from the database."""
        items = self._api.get_json(
            f"/spotify-tracks?limit={int(limit)}&offset=0"
        )
        out = []
        for it in items or []:
            out.append(
                {
                    "id": it.get("id"),
                    "spotify_id": it.get("spotify_id"),
                    "name": it.get("name"),
                    "artist": it.get("artist"),
                    "url": it.get("url"),
                    "added_by": it.get("added_by"),
                    "added_at": it.get("added_at"),
                }
            )
        return out

    def delete_by_id(self, track_id: int) -> None:
        """Delete a track by its database ID."""
        r = self._api._request("DELETE", f"/spotify-tracks/{track_id}")
        if r.status_code >= 400 and r.status_code != 404:
            raise ApiError(
                f"API delete track by id failed: {r.status_code} {r.text}"
            )

    def count_by_user(self, user_id: int) -> int:
        r = self._api._request(
            "GET", f"/spotify-tracks/count-by-user/{user_id}"
        )
        if r.status_code >= 400:
            raise ApiError(
                f"API count-by-user failed: {r.status_code} {r.text}"
            )
        return int((r.json() or {}).get("count") or 0)

    def exists_spotify_id(self, spotify_id: str) -> bool:
        r = self._api._request("GET", f"/spotify-tracks/exists/{spotify_id}")
        if r.status_code >= 400:
            raise ApiError(f"API exists failed: {r.status_code} {r.text}")
        return bool((r.json() or {}).get("exists"))

    def add_track(
        self,
        spotify_id: str,
        name: str,
        artist: str,
        url: Optional[str],
        added_by: int,
    ) -> bool:
        r = self._api.post_json(
            "/spotify-tracks",
            {
                "spotify_id": spotify_id,
                "name": name,
                "artist": artist,
                "url": url,
                "added_by": int(added_by),
            },
        )
        if r.status_code in {200, 201}:
            return True
        # unique constraint -> 500/409 depending on backend. Treat as duplicate.
        if r.status_code in {409, 422, 500}:
            return False
        raise ApiError(f"API create track failed: {r.status_code} {r.text}")

    def list_by_user(self, user_id: int, limit: int = 20):
        items = self._api.get_json(
            f"/spotify-tracks/by-user/{user_id}?limit={int(limit)}"
        )
        out = []
        for it in items or []:
            out.append(
                (
                    it.get("spotify_id"),
                    it.get("name"),
                    it.get("artist"),
                    it.get("url"),
                    it.get("added_at"),
                )
            )
        return out

    def delete_by_user(self, user_id: int, spotify_id: str) -> int:
        r = self._api._request(
            "DELETE", f"/spotify-tracks/by-user/{user_id}/{spotify_id}"
        )
        if r.status_code >= 400:
            raise ApiError(
                f"API delete track failed: {r.status_code} {r.text}"
            )
        return int((r.json() or {}).get("deleted") or 0)
