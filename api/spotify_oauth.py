from __future__ import annotations

import base64
import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, HTTPException
from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.responses import RedirectResponse


router = APIRouter(tags=["spotify-auth"])


def _env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    if v is None:
        return default
    v = v.strip()
    return v if v else default


def _store_path() -> Path:
    # Persist under /app/data inside container; allow override for local/dev.
    p = (_env("SPOTIFY_OAUTH_STORE_PATH") or "").strip()
    if p:
        return Path(p)
    data_dir = (_env("DATA_DIR") or "/app/data").strip() or "/app/data"
    return Path(data_dir) / "spotify_oauth.json"


@dataclass
class _TokenStore:
    refresh_token: str
    access_token: str
    expires_at: float


def _read_store() -> _TokenStore | None:
    path = _store_path()
    try:
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return None
        rt = str(raw.get("refresh_token") or "").strip()
        at = str(raw.get("access_token") or "").strip()
        exp = float(raw.get("expires_at") or 0)
        if not rt:
            return None
        return _TokenStore(refresh_token=rt, access_token=at, expires_at=exp)
    except Exception:
        return None


def _write_store(store: _TokenStore) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "refresh_token": store.refresh_token,
        "access_token": store.access_token,
        "expires_at": store.expires_at,
        "updated_at": int(time.time()),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _basic_auth_header(client_id: str, client_secret: str) -> str:
    raw = f"{client_id}:{client_secret}".encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def _required_oauth_config() -> tuple[str, str, str]:
    client_id = (_env("SPOTIFY_CLIENT_ID") or "").strip()
    client_secret = (_env("SPOTIFY_CLIENT_SECRET") or "").strip()
    redirect_uri = (_env("SPOTIFY_REDIRECT_URI") or "").strip()
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=500,
            detail=(
                "Spotify OAuth is not configured "
                "(missing SPOTIFY_CLIENT_ID/SPOTIFY_CLIENT_SECRET)"
            ),
        )
    if not redirect_uri:
        raise HTTPException(
            status_code=500,
            detail="Spotify OAuth is not configured (missing SPOTIFY_REDIRECT_URI)",
        )
    return client_id, client_secret, redirect_uri


def _scopes() -> str:
    # Minimal set for Web Playback SDK + player control.
    # Add more only if needed.
    return " ".join(
        [
            "streaming",
            "user-read-email",
            "user-read-playback-state",
            "user-modify-playback-state",
            "user-read-currently-playing",
            "user-read-private",
        ]
    )


@router.get("/spotify/login")
def spotify_login(request: Request) -> RedirectResponse:
    client_id, _client_secret, redirect_uri = _required_oauth_config()

    state = secrets.token_urlsafe(24)

    # Store state in a cookie so callback can validate.
    # Note: we intentionally do not set Secure=True unconditionally, because behind nginx
    # the app may see http scheme even if external is https.
    auth_url = (
        "https://accounts.spotify.com/authorize?"
        + urlencode(
            {
                "client_id": client_id,
                "response_type": "code",
                "redirect_uri": redirect_uri,
                "scope": _scopes(),
                "state": state,
                "show_dialog": "true",
            }
        )
    )

    resp = RedirectResponse(url=auth_url, status_code=302)
    resp.set_cookie(
        "noviy_spotify_state",
        state,
        httponly=True,
        samesite="lax",
        max_age=600,
        path="/",
    )
    return resp


@router.get("/spotify/callback")
def spotify_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> HTMLResponse:
    if error:
        return HTMLResponse(
            f"<h3>Spotify authorization failed</h3><pre>{error}</pre>",
            status_code=400,
        )

    if not code:
        return HTMLResponse("<h3>Missing code</h3>", status_code=400)

    cookie_state = (request.cookies.get("noviy_spotify_state") or "").strip()
    if not state or not cookie_state or state != cookie_state:
        return HTMLResponse("<h3>Invalid state</h3>", status_code=400)

    client_id, client_secret, redirect_uri = _required_oauth_config()

    auth = _basic_auth_header(client_id, client_secret)
    r = requests.post(
        "https://accounts.spotify.com/api/token",
        headers={"Authorization": f"Basic {auth}"},
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        },
        timeout=20,
    )

    if not r.ok:
        return HTMLResponse(
            f"<h3>Token exchange failed</h3><pre>{r.status_code} {r.text}</pre>",
            status_code=500,
        )

    data: dict[str, Any] = r.json() if r.content else {}
    refresh_token = str(data.get("refresh_token") or "").strip()
    access_token = str(data.get("access_token") or "").strip()
    expires_in = float(data.get("expires_in") or 3600)

    if not refresh_token:
        return HTMLResponse(
            "<h3>No refresh_token received</h3>"
            "<pre>Check that your Spotify app is configured correctly "
            "and you are using Authorization Code flow.</pre>",
            status_code=500,
        )

    expires_at = time.time() + expires_in
    _write_store(
        _TokenStore(
            refresh_token=refresh_token,
            access_token=access_token,
            expires_at=expires_at,
        )
    )

    resp = HTMLResponse(
        "<h3>Spotify connected</h3><p>You can close this tab and reload the overlay.</p>",
        status_code=200,
    )
    # clear state cookie
    resp.delete_cookie("noviy_spotify_state", path="/")
    return resp


def _refresh_access_token(refresh_token: str) -> _TokenStore:
    client_id, client_secret, _redirect_uri = _required_oauth_config()
    auth = _basic_auth_header(client_id, client_secret)

    r = requests.post(
        "https://accounts.spotify.com/api/token",
        headers={"Authorization": f"Basic {auth}"},
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=20,
    )
    if not r.ok:
        raise HTTPException(status_code=502, detail=f"Spotify refresh failed: {r.status_code}")

    data: dict[str, Any] = r.json() if r.content else {}
    access_token = str(data.get("access_token") or "").strip()
    expires_in = float(data.get("expires_in") or 3600)
    if not access_token:
        raise HTTPException(status_code=502, detail="Spotify refresh did not return access_token")

    return _TokenStore(
        refresh_token=refresh_token,
        access_token=access_token,
        expires_at=time.time() + expires_in,
    )


@router.get("/spotify/token")
def spotify_token() -> dict[str, Any]:
    store = _read_store()
    if store is None:
        raise HTTPException(
            status_code=409,
            detail="Spotify is not connected. Open /spotify/login to authorize.",
        )

    now = time.time()
    # refresh if missing/expired/near expiry
    if not store.access_token or now >= (store.expires_at - 30):
        store = _refresh_access_token(store.refresh_token)
        _write_store(store)

    return {
        "access_token": store.access_token,
        "expires_at": int(store.expires_at),
    }


@router.post("/spotify/reset")
def spotify_reset() -> dict[str, Any]:
    path = _store_path()
    existed = path.exists()
    try:
        path.unlink(missing_ok=True)
    except TypeError:
        # Python < 3.8 compatibility (missing_ok not available)
        try:
            if path.exists():
                path.unlink()
        except FileNotFoundError:
            pass

    return {"ok": True, "deleted": existed, "path": str(path)}
