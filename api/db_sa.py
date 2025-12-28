import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Iterable, Optional
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import (
    Boolean,
    DateTime,
    BigInteger,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    delete,
    false,
    func,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    sessionmaker,
)
from sqlalchemy.pool import StaticPool

logger = logging.getLogger("db")


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false()
    )
    is_blacklisted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false()
    )
    registered_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    last_active: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )


class Chat(Base):
    __tablename__ = "chats"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    type: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )


class Blacklist(Base):
    __tablename__ = "blacklist"

    tag: Mapped[str] = mapped_column(String, primary_key=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class SpotifyTrack(Base):
    __tablename__ = "spotify_tracks"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    spotify_id: Mapped[str] = mapped_column(
        String, nullable=False, unique=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    artist: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    added_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )


class ApiToken(Base):
    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    token_hash: Mapped[str] = mapped_column(
        String, nullable=False, unique=True
    )
    label: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )


class Prize(Base):
    __tablename__ = "slot"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(128), nullable=False)


class PrizeWin(Base):
    __tablename__ = "prize_wins"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    prize_name: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("slot.name", ondelete="RESTRICT"),
        nullable=False,
    )
    won_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )


class Voucher(Base):
    __tablename__ = "vouchers"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    code: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    # When user_id is NULL, the code is available for reuse.
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    issued_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    use_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    total_games: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )


class Photo(Base):
    __tablename__ = "photos"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    added_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )


def build_database_url(database_url: str, db_path: str) -> str:
    if database_url:
        return database_url
    return f"sqlite:///{db_path}"


@dataclass(frozen=True)
class Db:
    engine: Engine
    session_factory: sessionmaker[Session]

    def session(self) -> Session:
        return self.session_factory()


def create_db(database_url: str, db_path: str) -> Db:
    url = build_database_url(database_url, db_path)
    engine_kwargs = {"future": True}
    if url.startswith("sqlite") and (
        ":memory:" in url or "mode=memory" in url
    ):
        engine_kwargs.update(
            {
                "connect_args": {"check_same_thread": False},
                "poolclass": StaticPool,
            }
        )
    engine = create_engine(url, **engine_kwargs)
    SessionFactory = sessionmaker(
        bind=engine, expire_on_commit=False, future=True
    )

    def _redact_db_url(raw: str) -> str:
        try:
            u = urlsplit(raw)
        except Exception:
            return "<invalid-db-url>"
        if not u.scheme:
            return raw
        netloc = u.netloc
        if "@" in netloc:
            creds, host = netloc.rsplit("@", 1)
            if ":" in creds:
                user = creds.split(":", 1)[0]
                netloc = f"{user}:***@{host}"
        return urlunsplit((u.scheme, netloc, u.path, u.query, u.fragment))

    logger.info("SQLAlchemy engine created: %s", _redact_db_url(url))
    return Db(engine=engine, session_factory=SessionFactory)


# --- Repository layer (kept for tests and API implementation) ---


class UserRepo:
    def __init__(self, db: Db):
        self.db = db
        self._log = logging.getLogger(self.__class__.__name__)

    def upsert_user(
        self,
        user_id: int,
        username: Optional[str],
        first: Optional[str],
        last: Optional[str],
        is_admin: bool,
        is_blacklisted: bool = False,
    ) -> None:
        with self.db.session() as s:
            u = s.get(User, user_id)
            if u is None:
                u = User(id=user_id)
                s.add(u)
            u.username = username
            u.first_name = first
            u.last_name = last
            u.is_admin = bool(is_admin)
            u.is_blacklisted = bool(is_blacklisted)
            u.last_active = datetime.now(UTC)
            s.commit()
        self._log.debug(
            "Upsert user id=%s username=%s admin=%s blacklisted=%s",
            user_id,
            username,
            is_admin,
            is_blacklisted,
        )

    def exists(self, user_id: int) -> bool:
        with self.db.session() as s:
            return s.get(User, user_id) is not None

    def set_blacklisted(self, user_id: int, value: bool) -> None:
        with self.db.session() as s:
            u = s.get(User, user_id)
            if u is None:
                return
            u.is_blacklisted = bool(value)
            s.commit()
        self._log.info("User id=%s blacklisted=%s", user_id, value)

    def blacklist_by_username(self, username: str) -> int:
        uname = username.lstrip("@") if username else username
        if not uname:
            return 0
        with self.db.session() as s:
            q = select(User).where(
                func.lower(User.username) == func.lower(uname)
            )
            rows = list(s.scalars(q))
            for u in rows:
                u.is_blacklisted = True
            s.commit()
            return len(rows)

    def touch_activity(self, user_id: int) -> None:
        with self.db.session() as s:
            u = s.get(User, user_id)
            if u is None:
                return
            u.last_active = datetime.now(UTC)
            s.commit()
        self._log.debug("Touched activity for user id=%s", user_id)

    def get_activity(self, user_id: int) -> Optional[tuple]:
        with self.db.session() as s:
            u = s.get(User, user_id)
            if u is None:
                return None
            return (u.registered_at, u.last_active)

    def count(self) -> int:
        with self.db.session() as s:
            return int(s.scalar(select(func.count()).select_from(User)) or 0)

    def all_ids(self) -> Iterable[int]:
        with self.db.session() as s:
            for uid in s.scalars(select(User.id)):
                yield int(uid)


class ChatRepo:
    def __init__(self, db: Db):
        self.db = db
        self._log = logging.getLogger(self.__class__.__name__)

    def upsert_chat(
        self, chat_id: int, chat_type: str, title: Optional[str]
    ) -> None:
        with self.db.session() as s:
            c = s.get(Chat, chat_id)
            if c is None:
                c = Chat(chat_id=chat_id, type=chat_type, title=title)
                s.add(c)
            else:
                c.type = chat_type
                c.title = title
            s.commit()
        self._log.debug(
            "Upsert chat id=%s type=%s title=%s", chat_id, chat_type, title
        )

    def count(self) -> int:
        with self.db.session() as s:
            stmt = (
                select(func.count())
                .select_from(Chat)
                .where(Chat.type.in_(["group", "supergroup"]))
            )
            return int(s.scalar(stmt) or 0)

    def group_chat_ids(self) -> Iterable[int]:
        with self.db.session() as s:
            stmt = select(Chat.chat_id).where(
                Chat.type.in_(["group", "supergroup"])
            )
            for cid in s.scalars(stmt):
                yield int(cid)


class BlacklistRepo:
    def __init__(self, db: Db):
        self.db = db
        self._log = logging.getLogger(self.__class__.__name__)

    def add(self, tag: str, note: Optional[str] = None) -> None:
        tag_norm = tag.lstrip("@").lower()
        with self.db.session() as s:
            b = s.get(Blacklist, tag_norm)
            if b is None:
                b = Blacklist(tag=tag_norm)
                s.add(b)
            b.note = note
            s.commit()
        self._log.info("Blacklist add tag=@%s", tag_norm)

    def remove(self, tag: str) -> None:
        tag_norm = tag.lstrip("@").lower()
        with self.db.session() as s:
            b = s.get(Blacklist, tag_norm)
            if b is not None:
                s.delete(b)
                s.commit()
        self._log.info("Blacklist remove tag=@%s", tag_norm)

    def list(self) -> Iterable[tuple]:
        with self.db.session() as s:
            stmt = select(
                Blacklist.tag, Blacklist.note, Blacklist.created_at
            ).order_by(Blacklist.created_at.desc())
            for t, n, c in s.execute(stmt).all():
                yield (t, n, c)

    def matches(self, username: Optional[str]) -> bool:
        if not username:
            return False
        uname = username.lstrip("@").lower()
        with self.db.session() as s:
            return s.get(Blacklist, uname) is not None


class SettingsRepo:
    def __init__(self, db: Db):
        self.db = db
        self._log = logging.getLogger(self.__class__.__name__)

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self.db.session() as s:
            row = s.get(Setting, key)
            if row is None:
                return default
            return row.value if row.value is not None else default

    def set(self, key: str, value: str) -> None:
        with self.db.session() as s:
            row = s.get(Setting, key)
            if row is None:
                row = Setting(key=key, value=value)
                s.add(row)
            else:
                row.value = value
            s.commit()
        self._log.info("Setting %s=%s", key, value)


class SpotifyTracksRepo:
    def __init__(self, db: Db):
        self.db = db
        self._log = logging.getLogger(self.__class__.__name__)

    def count_by_user(self, user_id: int) -> int:
        with self.db.session() as s:
            stmt = (
                select(func.count())
                .select_from(SpotifyTrack)
                .where(SpotifyTrack.added_by == user_id)
            )
            return int(s.scalar(stmt) or 0)

    def exists_spotify_id(self, spotify_id: str) -> bool:
        with self.db.session() as s:
            stmt = (
                select(SpotifyTrack.id)
                .where(SpotifyTrack.spotify_id == spotify_id)
                .limit(1)
            )
            return s.scalar(stmt) is not None

    def add_track(
        self,
        spotify_id: str,
        name: str,
        artist: str,
        url: Optional[str],
        added_by: int,
    ) -> bool:
        try:
            with self.db.session() as s:
                s.add(
                    SpotifyTrack(
                        spotify_id=spotify_id,
                        name=name,
                        artist=artist,
                        url=url,
                        added_by=added_by,
                    )
                )
                s.commit()
            self._log.info(
                "Track added spotify_id=%s by user_id=%s", spotify_id, added_by
            )
            return True
        except IntegrityError:
            return False

    def list_by_user(self, user_id: int, limit: int = 20):
        with self.db.session() as s:
            stmt = (
                select(
                    SpotifyTrack.spotify_id,
                    SpotifyTrack.name,
                    SpotifyTrack.artist,
                    SpotifyTrack.url,
                    SpotifyTrack.added_at,
                )
                .where(SpotifyTrack.added_by == user_id)
                .order_by(SpotifyTrack.added_at.desc())
                .limit(limit)
            )
            return list(s.execute(stmt).all())

    def delete_by_user(self, user_id: int, spotify_id: str) -> int:
        with self.db.session() as s:
            stmt = delete(SpotifyTrack).where(
                SpotifyTrack.added_by == user_id,
                SpotifyTrack.spotify_id == spotify_id,
            )
            res = s.execute(stmt)
            s.commit()
            deleted = int(getattr(res, "rowcount", 0) or 0)
            if deleted:
                self._log.info(
                    "Track deleted spotify_id=%s by user_id=%s",
                    spotify_id,
                    user_id,
                )
            return deleted
