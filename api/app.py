from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import logging
import random
import os
import time
from contextlib import asynccontextmanager
from contextlib import contextmanager
from typing import Any, Generator

from dotenv import load_dotenv

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.responses import Response

from api.db import Db, init_db
from api.db_sa import ApiToken, Blacklist, Chat, Setting, SpotifyTrack, User

from api.photos import router as photos_router
from api.spotify_oauth import router as spotify_oauth_router
from api.slot import router as prizes_router
from api.vouchers import router as vouchers_router

from .schemas import (
    BlacklistByUsername,
    BlacklistByUsernameOut,
    BlacklistCreate,
    BlacklistOut,
    BlacklistUpdate,
    ChatCreate,
    ChatOut,
    ChatUpdate,
    CountOut,
    DeletedOut,
    ExistsOut,
    SettingOut,
    SettingUpsert,
    SpotifyTrackCreate,
    SpotifyTrackOut,
    SpotifyTrackUpdate,
    UserCreate,
    UserOut,
    UserUpdate,
)


@dataclass
class _PlayerController:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    playing: bool = False
    index: int | None = None
    playlist: list[SpotifyTrack] = field(default_factory=list)
    clients: set[WebSocket] = field(default_factory=set)
    version: int = 0

    def _current(self) -> SpotifyTrack | None:
        if self.index is None:
            return None
        if self.index < 0 or self.index >= len(self.playlist):
            return None
        return self.playlist[self.index]


def _track_to_dict(track: SpotifyTrack) -> dict[str, Any]:
    return {
        "id": int(track.id),
        "spotify_id": track.spotify_id,
        "name": track.name,
        "artist": track.artist,
        "url": track.url,
        "added_by": int(track.added_by),
        "added_at": track.added_at.isoformat() if track.added_at else None,
    }


def _player_state_payload(ctrl: _PlayerController) -> dict[str, Any]:
    current = ctrl._current()
    return {
        "type": "state",
        "version": int(ctrl.version),
        "playing": bool(ctrl.playing),
        "index": ctrl.index,
        "current": _track_to_dict(current) if current is not None else None,
        "playlist": [_track_to_dict(t) for t in ctrl.playlist],
    }


def create_app(*, db: Db | None = None) -> FastAPI:
    # Allow configuring API via a local .env file when running without Docker/Compose.
    # In Compose, env_file/environment already populate os.environ; load_dotenv is harmless.
    load_dotenv(override=False)

    def _env(name: str, default: str | None = None) -> str | None:
        v = os.environ.get(name)
        if v is None:
            return default
        v = v.strip()
        return v if v else default

    def _ensure_logging_configured() -> None:
        root = logging.getLogger()
        if root.handlers:
            return
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        )

    _ensure_logging_configured()
    logger = logging.getLogger("api")

    max_tracks_raw = (_env("MAX_TRACKS_PER_USER", "5") or "5").strip()
    try:
        max_tracks_per_user = int(max_tracks_raw)
        if max_tracks_per_user < 0:
            max_tracks_per_user = 5
    except Exception:
        logger.error("Invalid MAX_TRACKS_PER_USER value: %r", max_tracks_raw)
        max_tracks_per_user = 5

    _DEFAULT_SETTINGS: dict[str, str] = {
        # Common bot behavior toggles
        "allow_new_users": "1",
        # Tracks feature
        "max_tracks_per_user": str(max_tracks_per_user),
        # Tracks closure feature (empty means "not scheduled")
        "tracks_close_at_ts": "",
        "tracks_close_announced_for_ts": "0",
    }

    def _ensure_default_settings(s: Session) -> None:
        changed = False
        for key, value in _DEFAULT_SETTINGS.items():
            if s.get(Setting, key) is None:
                s.add(Setting(key=key, value=value))
                changed = True
        if changed:
            s.commit()

    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _extract_env_token() -> str | None:
        raw = (_env("BOT_API_TOKEN", "") or "").strip()
        if not raw:
            return None
        if raw.lower().startswith("bearer "):
            raw = raw[7:].strip()
        return raw if raw else None

    def _ensure_env_api_token(s: Session) -> None:
        token = _extract_env_token()
        if not token:
            return

        token_hash = _hash_token(token)
        exists = (
            s.scalar(
                select(ApiToken.id).where(ApiToken.token_hash == token_hash)
            )
            is not None
        )
        if exists:
            logger.info(
                "BOT_API_TOKEN from env already exists in DB (token_hash_prefix=%s)",
                token_hash[:8],
            )
            return

        s.add(ApiToken(token_hash=token_hash, label="env:BOT_API_TOKEN"))
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            logger.info(
                "BOT_API_TOKEN from env already exists in DB (race) (token_hash_prefix=%s)",
                token_hash[:8],
            )
        else:
            logger.info(
                "Added BOT_API_TOKEN from env to DB (token_hash_prefix=%s)",
                token_hash[:8],
            )

    def _extract_http_token(request: Request) -> str | None:
        auth = (request.headers.get("authorization") or "").strip()
        if auth.lower().startswith("bearer "):
            v = auth[7:].strip()
            return v if v else None
        x = (request.headers.get("x-api-token") or "").strip()
        if x:
            return x

        # Allow token in query string for browser-driven flows where setting headers is
        # inconvenient.
        # Limit this to Spotify OAuth helper endpoints only.
        p = request.url.path
        if p in {
            "/spotify/login",
            "/spotify/token",
            "/spotify/reset",
            "/api/spotify/login",
            "/api/spotify/token",
            "/api/spotify/reset",
        }:
            q = (
                request.query_params.get("token")
                or request.query_params.get("api_token")
                or ""
            ).strip()
            if q.lower().startswith("bearer "):
                q = q[7:].strip()
            return q if q else None

        return None

    def _check_http_token(request: Request) -> tuple[bool, str | None]:
        token = _extract_http_token(request)
        if not token:
            return (False, "Missing API token")
        token_hash = _hash_token(token)
        try:
            with request.app.state.db.session() as s:
                row = s.scalar(
                    select(ApiToken).where(ApiToken.token_hash == token_hash)
                )
                if row is None:
                    return (False, "Invalid API token")
        except Exception:
            # Never turn auth failures into 500.
            return (False, "Unauthorized")
        return (True, None)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("API starting")
        if db is None:
            database_url = (_env("DATABASE_URL", "") or "").strip()
            db_path = (
                _env("DB_PATH", "database.sqlite3") or "database.sqlite3"
            ).strip()
            app.state.db = init_db(database_url=database_url, db_path=db_path)
            logger.info("DB initialized for API (db_path=%s)", db_path)
        else:
            app.state.db = db
            logger.info("DB injected for API")

        try:
            with app.state.db.session() as s:
                _ensure_default_settings(s)
                _ensure_env_api_token(s)
        except Exception:
            logger.exception("Failed to ensure default settings")
        yield
        logger.info("API stopping")

    app = FastAPI(title="noviy_2026_bot API", lifespan=lifespan)
    app.state.player = _PlayerController()

    app.include_router(prizes_router)
    app.include_router(vouchers_router)
    app.include_router(photos_router)
    app.include_router(spotify_oauth_router)

    if db is not None:
        app.state.db = db
        try:
            with db.session() as s:
                _ensure_default_settings(s)
        except Exception:
            logger.exception("Failed to ensure default settings")

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next) -> Response:
        # Healthcheck should work without a token.
        # Keep both variants for safety (direct uvicorn hits vs nginx-stripped paths).
        if request.url.path in {"/health", "/api/health"}:
            return await call_next(request)

        # Spotify OAuth callback is invoked by Spotify and cannot include our API token.
        if request.url.path in {"/spotify/callback", "/api/spotify/callback"}:
            return await call_next(request)

        ok, err = _check_http_token(request)
        if not ok:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": err or "Unauthorized"},
            )
        return await call_next(request)

    @app.middleware("http")
    async def access_log_middleware(request: Request, call_next) -> Response:
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            logger.exception(
                "%s %s -> 500 (%.1fms)",
                request.method,
                request.url.path,
                elapsed_ms,
            )
            raise

        elapsed_ms = (time.perf_counter() - start) * 1000.0
        logger.info(
            "%s %s -> %s (%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response

    def _load_playlist(s: Session) -> list[SpotifyTrack]:
        stmt = select(SpotifyTrack).order_by(
            SpotifyTrack.added_at.asc(), SpotifyTrack.id.asc()
        )
        return list(s.scalars(stmt))

    async def _broadcast_player_state(
        ctrl: _PlayerController, *, bump: bool = False
    ) -> None:
        if bump:
            ctrl.version += 1
        payload = _player_state_payload(ctrl)
        dead: list[WebSocket] = []
        for ws in list(ctrl.clients):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            ctrl.clients.discard(ws)

    @app.websocket("/ws/player")
    async def ws_player(ws: WebSocket) -> None:
        await ws.accept()
        ctrl: _PlayerController = app.state.player
        logger.info(
            "WS /ws/player connected client=%s", getattr(ws, "client", None)
        )

        async with ctrl.lock:
            ctrl.clients.add(ws)
            with app.state.db.session() as s:
                ctrl.playlist = _load_playlist(s)
            if ctrl.index is None and ctrl.playlist:
                ctrl.index = 0
            if ctrl.index is not None and ctrl.index >= len(ctrl.playlist):
                ctrl.index = 0 if ctrl.playlist else None
            ctrl.version += 1
            await ws.send_json(_player_state_payload(ctrl))

        try:
            while True:
                msg = await ws.receive_json()
                op = (
                    (msg.get("op") or "").strip().lower()
                    if isinstance(msg, dict)
                    else ""
                )
                if not op:
                    await ws.send_json(
                        {"type": "error", "message": "Missing op"}
                    )
                    continue

                async with ctrl.lock:
                    if op in {"ping"}:
                        await ws.send_json({"type": "pong"})
                        continue

                    if op in {"get_state", "state"}:
                        await ws.send_json(_player_state_payload(ctrl))
                        continue

                    if op in {"get_playlist", "playlist"}:
                        await ws.send_json(
                            {
                                "type": "playlist",
                                "index": ctrl.index,
                                "playlist": [
                                    _track_to_dict(t) for t in ctrl.playlist
                                ],
                            }
                        )
                        continue

                    if op in {"refresh_playlist", "refresh"}:
                        with app.state.db.session() as s:
                            ctrl.playlist = _load_playlist(s)
                        if ctrl.index is None and ctrl.playlist:
                            ctrl.index = 0
                        if ctrl.index is not None and ctrl.index >= len(
                            ctrl.playlist
                        ):
                            ctrl.index = 0 if ctrl.playlist else None
                        await _broadcast_player_state(ctrl, bump=True)
                        continue

                    if op == "play":
                        ctrl.playing = True
                        if ctrl.index is None and ctrl.playlist:
                            ctrl.index = 0
                        await _broadcast_player_state(ctrl, bump=True)
                        continue

                    if op == "pause":
                        ctrl.playing = False
                        await _broadcast_player_state(ctrl, bump=True)
                        continue

                    if op in {"next", "next_track"}:
                        if ctrl.playlist:
                            if ctrl.index is None:
                                ctrl.index = 0
                            else:
                                ctrl.index = min(
                                    ctrl.index + 1, len(ctrl.playlist) - 1
                                )
                        await _broadcast_player_state(ctrl, bump=True)
                        continue

                    if op in {"prev", "previous", "prev_track"}:
                        if ctrl.playlist:
                            if ctrl.index is None:
                                ctrl.index = 0
                            else:
                                ctrl.index = max(ctrl.index - 1, 0)
                        await _broadcast_player_state(ctrl, bump=True)
                        continue

                    if op in {"set_index", "seek"}:
                        try:
                            idx = int(msg.get("index"))
                        except Exception:
                            await ws.send_json(
                                {"type": "error", "message": "Invalid index"}
                            )
                            continue
                        if idx < 0 or idx >= len(ctrl.playlist):
                            await ws.send_json(
                                {
                                    "type": "error",
                                    "message": "Index out of range",
                                }
                            )
                            continue
                        ctrl.index = idx
                        await _broadcast_player_state(ctrl, bump=True)
                        continue

                    await ws.send_json(
                        {"type": "error", "message": f"Unknown op: {op}"}
                    )
        except WebSocketDisconnect:
            pass
        finally:
            async with ctrl.lock:
                ctrl.clients.discard(ws)
            logger.info("WS /ws/player disconnected")

    # ---- Player control endpoints (admin via API token) ----

    @app.post("/player/play")
    async def player_play(request: Request) -> dict:
        ctrl: _PlayerController = app.state.player
        async with ctrl.lock:
            ctrl.playing = True
            if ctrl.index is None and ctrl.playlist:
                ctrl.index = 0
            await _broadcast_player_state(ctrl, bump=True)
            return _player_state_payload(ctrl)

    @app.post("/player/pause")
    async def player_pause(request: Request) -> dict:
        ctrl: _PlayerController = app.state.player
        async with ctrl.lock:
            ctrl.playing = False
            await _broadcast_player_state(ctrl, bump=True)
            return _player_state_payload(ctrl)

    @app.post("/player/shuffle")
    async def player_shuffle(request: Request) -> dict:
        ctrl: _PlayerController = app.state.player
        async with ctrl.lock:
            if ctrl.playlist:
                random.shuffle(ctrl.playlist)
                ctrl.index = 0 if ctrl.playlist else None
            await _broadcast_player_state(ctrl, bump=True)
            return _player_state_payload(ctrl)

    @app.post("/player/prev")
    async def player_prev(request: Request) -> dict:
        ctrl: _PlayerController = app.state.player
        async with ctrl.lock:
            if ctrl.playlist:
                if ctrl.index is None:
                    ctrl.index = 0
                else:
                    ctrl.index = (ctrl.index - 1) % len(ctrl.playlist)
            await _broadcast_player_state(ctrl, bump=True)
            return _player_state_payload(ctrl)

    @app.post("/player/next")
    async def player_next(request: Request) -> dict:
        ctrl: _PlayerController = app.state.player
        async with ctrl.lock:
            if ctrl.playlist:
                if ctrl.index is None:
                    ctrl.index = 0
                else:
                    ctrl.index = (ctrl.index + 1) % len(ctrl.playlist)
            await _broadcast_player_state(ctrl, bump=True)
            return _player_state_payload(ctrl)

    @contextmanager
    def _session() -> Generator[Session, None, None]:
        s = app.state.db.session()
        try:
            yield s
        finally:
            s.close()

    def get_session() -> Generator[Session, None, None]:
        with _session() as s:
            yield s

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    # ---- Users ----

    @app.get("/users", response_model=list[UserOut])
    def list_users(
        limit: int = 100,
        offset: int = 0,
        s: Session = Depends(get_session),
    ) -> list[User]:
        stmt = select(User).order_by(User.id).limit(limit).offset(offset)
        return list(s.scalars(stmt))

    @app.get("/users/{user_id}", response_model=UserOut)
    def get_user(user_id: int, s: Session = Depends(get_session)) -> User:
        obj = s.get(User, user_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="User not found")
        return obj

    @app.post(
        "/users", response_model=UserOut, status_code=status.HTTP_201_CREATED
    )
    def create_user(
        payload: UserCreate, s: Session = Depends(get_session)
    ) -> User:
        existing = s.get(User, payload.id)
        if existing is not None:
            raise HTTPException(status_code=409, detail="User already exists")
        obj = User(
            id=payload.id,
            username=payload.username,
            first_name=payload.first_name,
            last_name=payload.last_name,
            is_admin=bool(payload.is_admin),
            is_blacklisted=bool(payload.is_blacklisted),
        )
        s.add(obj)
        s.commit()
        s.refresh(obj)
        return obj

    @app.put("/users/{user_id}", response_model=UserOut)
    def update_user(
        user_id: int,
        payload: UserUpdate,
        s: Session = Depends(get_session),
    ) -> User:
        obj = s.get(User, user_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="User not found")
        if payload.username is not None:
            obj.username = payload.username
        if payload.first_name is not None:
            obj.first_name = payload.first_name
        if payload.last_name is not None:
            obj.last_name = payload.last_name
        if payload.is_admin is not None:
            obj.is_admin = bool(payload.is_admin)
        if payload.is_blacklisted is not None:
            obj.is_blacklisted = bool(payload.is_blacklisted)
        obj.last_active = datetime.now(UTC)
        s.commit()
        s.refresh(obj)
        return obj

    @app.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_user(user_id: int, s: Session = Depends(get_session)) -> None:
        obj = s.get(User, user_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="User not found")
        s.delete(obj)
        s.commit()
        return None

    @app.post(
        "/users/blacklist-by-username", response_model=BlacklistByUsernameOut
    )
    def blacklist_by_username(
        payload: BlacklistByUsername, s: Session = Depends(get_session)
    ) -> BlacklistByUsernameOut:
        uname = (payload.username or "").strip().lstrip("@").lower()
        if not uname:
            return BlacklistByUsernameOut(updated=0)
        stmt = select(User).where(User.username.is_not(None))
        rows = [
            u for u in s.scalars(stmt) if (u.username or "").lower() == uname
        ]
        for u in rows:
            u.is_blacklisted = True
            u.last_active = datetime.now(UTC)
        s.commit()
        return BlacklistByUsernameOut(updated=len(rows))

    # ---- Chats ----

    @app.get("/chats", response_model=list[ChatOut])
    def list_chats(
        limit: int = 100,
        offset: int = 0,
        s: Session = Depends(get_session),
    ) -> list[Chat]:
        stmt = select(Chat).order_by(Chat.chat_id).limit(limit).offset(offset)
        return list(s.scalars(stmt))

    @app.get("/chats/group-ids", response_model=list[int])
    def list_group_chat_ids(s: Session = Depends(get_session)) -> list[int]:
        stmt = select(Chat.chat_id).where(
            Chat.type.in_(["group", "supergroup"])
        )
        return [int(cid) for cid in s.scalars(stmt)]

    @app.get("/chats/group-count", response_model=CountOut)
    def count_group_chats(s: Session = Depends(get_session)) -> CountOut:
        stmt = (
            select(Chat.chat_id)
            .where(Chat.type.in_(["group", "supergroup"]))
            .order_by(Chat.chat_id)
        )
        return CountOut(count=len(list(s.scalars(stmt))))

    @app.get("/chats/{chat_id}", response_model=ChatOut)
    def get_chat(chat_id: int, s: Session = Depends(get_session)) -> Chat:
        obj = s.get(Chat, chat_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        return obj

    @app.post(
        "/chats", response_model=ChatOut, status_code=status.HTTP_201_CREATED
    )
    def create_chat(
        payload: ChatCreate, s: Session = Depends(get_session)
    ) -> Chat:
        existing = s.get(Chat, payload.chat_id)
        if existing is not None:
            raise HTTPException(status_code=409, detail="Chat already exists")
        obj = Chat(
            chat_id=payload.chat_id, type=payload.type, title=payload.title
        )
        s.add(obj)
        s.commit()
        s.refresh(obj)
        return obj

    @app.put("/chats/{chat_id}", response_model=ChatOut)
    def update_chat(
        chat_id: int, payload: ChatUpdate, s: Session = Depends(get_session)
    ) -> Chat:
        obj = s.get(Chat, chat_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        if payload.type is not None:
            obj.type = payload.type
        if payload.title is not None:
            obj.title = payload.title
        s.commit()
        s.refresh(obj)
        return obj

    @app.delete("/chats/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_chat(chat_id: int, s: Session = Depends(get_session)) -> None:
        obj = s.get(Chat, chat_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        s.delete(obj)
        s.commit()
        return None

    # ---- Blacklist ----

    @app.get("/blacklist", response_model=list[BlacklistOut])
    def list_blacklist(
        limit: int = 100,
        offset: int = 0,
        s: Session = Depends(get_session),
    ) -> list[Blacklist]:
        stmt = (
            select(Blacklist)
            .order_by(Blacklist.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(s.scalars(stmt))

    @app.get("/blacklist/{tag}", response_model=BlacklistOut)
    def get_blacklist(
        tag: str, s: Session = Depends(get_session)
    ) -> Blacklist:
        key = tag.lstrip("@").lower()
        obj = s.get(Blacklist, key)
        if obj is None:
            raise HTTPException(status_code=404, detail="Tag not found")
        return obj

    @app.post(
        "/blacklist",
        response_model=BlacklistOut,
        status_code=status.HTTP_201_CREATED,
    )
    def create_blacklist(
        payload: BlacklistCreate, s: Session = Depends(get_session)
    ) -> Blacklist:
        key = payload.tag.lstrip("@").lower()
        existing = s.get(Blacklist, key)
        if existing is not None:
            raise HTTPException(status_code=409, detail="Tag already exists")
        obj = Blacklist(tag=key, note=payload.note)
        s.add(obj)
        s.commit()
        s.refresh(obj)
        return obj

    @app.put("/blacklist/{tag}", response_model=BlacklistOut)
    def update_blacklist(
        tag: str, payload: BlacklistUpdate, s: Session = Depends(get_session)
    ) -> Blacklist:
        key = tag.lstrip("@").lower()
        obj = s.get(Blacklist, key)
        if obj is None:
            raise HTTPException(status_code=404, detail="Tag not found")
        if payload.note is not None:
            obj.note = payload.note
        s.commit()
        s.refresh(obj)
        return obj

    @app.delete("/blacklist/{tag}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_blacklist(tag: str, s: Session = Depends(get_session)) -> None:
        key = tag.lstrip("@").lower()
        obj = s.get(Blacklist, key)
        if obj is None:
            raise HTTPException(status_code=404, detail="Tag not found")
        s.delete(obj)
        s.commit()
        return None

    # ---- Settings ----

    @app.get("/settings", response_model=list[SettingOut])
    def list_settings(
        limit: int = 200,
        offset: int = 0,
        s: Session = Depends(get_session),
    ) -> list[Setting]:
        stmt = (
            select(Setting).order_by(Setting.key).limit(limit).offset(offset)
        )
        return list(s.scalars(stmt))

    @app.get("/settings/{key}", response_model=SettingOut)
    def get_setting(key: str, s: Session = Depends(get_session)) -> Setting:
        obj = s.get(Setting, key)
        if obj is None:
            raise HTTPException(status_code=404, detail="Setting not found")
        return obj

    @app.put("/settings/{key}", response_model=SettingOut)
    def upsert_setting(
        key: str, payload: SettingUpsert, s: Session = Depends(get_session)
    ) -> Setting:
        obj = s.get(Setting, key)
        if obj is None:
            obj = Setting(key=key, value=payload.value)
            s.add(obj)
        else:
            obj.value = payload.value
        s.commit()
        s.refresh(obj)
        return obj

    @app.delete("/settings/{key}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_setting(key: str, s: Session = Depends(get_session)) -> None:
        obj = s.get(Setting, key)
        if obj is None:
            raise HTTPException(status_code=404, detail="Setting not found")
        s.delete(obj)
        s.commit()
        return None

    # ---- Spotify tracks ----

    @app.get("/spotify-tracks", response_model=list[SpotifyTrackOut])
    def list_spotify_tracks(
        limit: int = 100,
        offset: int = 0,
        s: Session = Depends(get_session),
    ) -> list[SpotifyTrack]:
        stmt = (
            select(SpotifyTrack)
            .order_by(SpotifyTrack.added_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(s.scalars(stmt))

    @app.get("/spotify-tracks/{track_id}", response_model=SpotifyTrackOut)
    def get_spotify_track(
        track_id: int, s: Session = Depends(get_session)
    ) -> SpotifyTrack:
        obj = s.get(SpotifyTrack, track_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="Track not found")
        return obj

    @app.post(
        "/spotify-tracks",
        response_model=SpotifyTrackOut,
        status_code=status.HTTP_201_CREATED,
    )
    def create_spotify_track(
        payload: SpotifyTrackCreate, s: Session = Depends(get_session)
    ) -> SpotifyTrack:
        obj = SpotifyTrack(
            spotify_id=payload.spotify_id,
            name=payload.name,
            artist=payload.artist,
            url=payload.url,
            added_by=payload.added_by,
        )
        s.add(obj)
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            raise HTTPException(status_code=409, detail="Track already exists")
        s.refresh(obj)
        return obj

    @app.put("/spotify-tracks/{track_id}", response_model=SpotifyTrackOut)
    def update_spotify_track(
        track_id: int,
        payload: SpotifyTrackUpdate,
        s: Session = Depends(get_session),
    ) -> SpotifyTrack:
        obj = s.get(SpotifyTrack, track_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="Track not found")
        if payload.spotify_id is not None:
            obj.spotify_id = payload.spotify_id
        if payload.name is not None:
            obj.name = payload.name
        if payload.artist is not None:
            obj.artist = payload.artist
        if payload.url is not None:
            obj.url = payload.url
        if payload.added_by is not None:
            obj.added_by = int(payload.added_by)
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            raise HTTPException(status_code=409, detail="Track already exists")
        s.refresh(obj)
        return obj

    @app.delete(
        "/spotify-tracks/{track_id}", status_code=status.HTTP_204_NO_CONTENT
    )
    def delete_spotify_track(
        track_id: int, s: Session = Depends(get_session)
    ) -> None:
        obj = s.get(SpotifyTrack, track_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="Track not found")
        s.delete(obj)
        s.commit()
        return None

    @app.get("/spotify-tracks/exists/{spotify_id}", response_model=ExistsOut)
    def spotify_track_exists(
        spotify_id: str, s: Session = Depends(get_session)
    ) -> ExistsOut:
        stmt = (
            select(SpotifyTrack.id)
            .where(SpotifyTrack.spotify_id == spotify_id)
            .limit(1)
        )
        return ExistsOut(exists=(s.scalar(stmt) is not None))

    @app.get(
        "/spotify-tracks/count-by-user/{user_id}", response_model=CountOut
    )
    def spotify_tracks_count_by_user(
        user_id: int, s: Session = Depends(get_session)
    ) -> CountOut:
        stmt = (
            select(SpotifyTrack.id)
            .where(SpotifyTrack.added_by == user_id)
            .order_by(SpotifyTrack.id)
        )
        return CountOut(count=len(list(s.scalars(stmt))))

    @app.get(
        "/spotify-tracks/by-user/{user_id}",
        response_model=list[SpotifyTrackOut],
    )
    def list_spotify_tracks_by_user(
        user_id: int,
        limit: int = 20,
        s: Session = Depends(get_session),
    ) -> list[SpotifyTrack]:
        stmt = (
            select(SpotifyTrack)
            .where(SpotifyTrack.added_by == user_id)
            .order_by(SpotifyTrack.added_at.desc(), SpotifyTrack.id.desc())
            .limit(limit)
        )
        return list(s.scalars(stmt))

    @app.delete(
        "/spotify-tracks/by-user/{user_id}/{spotify_id}",
        response_model=DeletedOut,
    )
    def delete_spotify_track_by_user(
        user_id: int,
        spotify_id: str,
        s: Session = Depends(get_session),
    ) -> DeletedOut:
        stmt = select(SpotifyTrack).where(
            SpotifyTrack.added_by == user_id,
            SpotifyTrack.spotify_id == spotify_id,
        )
        rows = list(s.scalars(stmt))
        for r in rows:
            s.delete(r)
        s.commit()
        return DeletedOut(deleted=len(rows))

    return app


app = create_app()
