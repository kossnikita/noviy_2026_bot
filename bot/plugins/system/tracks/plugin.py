import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.api_repos import (
    ApiSettings,
    ChatRepo,
    SettingsRepo,
    SpotifyTracksRepo,
    _Api,
    _api_base_url_from_env,
)
from bot.config import load_config
from bot.integrations.spotify_client import SpotifyClient
from bot.plugins.system.tracks.tracks_closure import run_tracks_closure_scheduler


_LOG = logging.getLogger("tracks")

_TRACKS_CLOSE_TS_KEY = "tracks_close_at_ts"
_MAX_TRACKS_PER_USER_KEY = "max_tracks_per_user"
_TRACKS_ADMIN_CB = "tracks:admin"
_TRACKS_MENU_CB = "tracks:menu"


def _get_close_ts(settings: SettingsRepo) -> int | None:
    raw = (settings.get(_TRACKS_CLOSE_TS_KEY, "") or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _is_closed(settings: SettingsRepo) -> tuple[bool, int | None]:
    close_ts = _get_close_ts(settings)
    if close_ts is None:
        return (False, None)
    now_ts = int(datetime.now(timezone.utc).timestamp())
    return (now_ts >= close_ts, close_ts)


def _closed_text(close_ts: int) -> str:
    dt = datetime.fromtimestamp(close_ts, tz=timezone.utc)
    return "Список треков закрыт для изменений.\n" f"Время закрытия (UTC): {dt:%Y-%m-%d %H:%M}"


def _get_max_tracks_per_user(settings: SettingsRepo, *, fallback: int) -> int:
    raw = (settings.get(_MAX_TRACKS_PER_USER_KEY, "") or "").strip()
    try:
        v = int(raw)
        if v > 0:
            return v
    except Exception:
        pass
    return int(fallback)


class _TrackStates(StatesGroup):
    waiting_query = State()
    waiting_confirm = State()


def _confirm_kb(spotify_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Да, добавить",
                    callback_data=f"track:add:{spotify_id}",
                ),
                InlineKeyboardButton(text="❌ Нет", callback_data="track:cancel"),
            ]
        ]
    )


def _delete_kb(spotify_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🗑 Удалить",
                    callback_data=f"track:del:{spotify_id}",
                )
            ]
        ]
    )


class Plugin:
    """System plugin: track adding/listing.

    Registers /track and /mytracks commands and related callbacks.
    """

    name = "Tracks"

    def user_menu_button(self):
        return ("🎵 Треки", _TRACKS_MENU_CB)

    def admin_menu_button(self):
        return ("🎵 Треки (настройки)", _TRACKS_ADMIN_CB)

    def __init__(self) -> None:
        cfg = load_config()

        api_base_url = _api_base_url_from_env()
        api = _Api(ApiSettings(base_url=api_base_url, timeout_s=5.0))

        self._settings = SettingsRepo(api)
        self._tracks = SpotifyTracksRepo(api)
        self._chats = ChatRepo(api)
        self._spotify = SpotifyClient(cfg.spotify_client_id, cfg.spotify_client_secret)
        self._max_tracks_per_user = int(cfg.max_tracks_per_user)

        self._scheduler_task: asyncio.Task[None] | None = None

    def start(self, bot: Bot) -> asyncio.Task[None] | None:
        if self._scheduler_task is not None and not self._scheduler_task.done():
            return self._scheduler_task

        self._scheduler_task = asyncio.create_task(
            run_tracks_closure_scheduler(bot, self._settings, self._chats)
        )
        return self._scheduler_task

    def register_user(self, router: Router) -> None:
        _LOG.info("Tracks plugin registered: /track /mytracks")

        async def _handle_query(message: Message, state: FSMContext, query: str) -> None:
            closed, close_ts = _is_closed(self._settings)
            if closed and close_ts is not None:
                await message.answer(_closed_text(close_ts))
                return

            if query.startswith("/"):
                await message.answer(
                    "Пожалуйста, отправьте ссылку Spotify или название трека, а не команду."
                )
                return

            if not self._spotify.is_configured():
                await message.answer(
                    "Spotify не настроен. Нужны SPOTIFY_CLIENT_ID и SPOTIFY_CLIENT_SECRET."
                )
                return

            if message.from_user is None:
                return

            user_id = message.from_user.id
            max_tracks = _get_max_tracks_per_user(
                self._settings, fallback=self._max_tracks_per_user
            )
            if self._tracks.count_by_user(user_id) >= max_tracks:
                await message.answer(
                    f"Лимит треков: {max_tracks}. "
                    "Сначала удалите один из своих треков через /mytracks."
                )
                return

            try:
                spotify_id = SpotifyClient.parse_spotify_track_id(query)
                if spotify_id:
                    track = self._spotify.get_track(spotify_id)
                else:
                    track = self._spotify.search_track(query)
                    if not track:
                        await message.answer(
                            "Не смог найти трек в Spotify. "
                            "Попробуйте ссылку или более точный запрос."
                        )
                        return

                if self._tracks.exists_spotify_id(track.spotify_id):
                    await message.answer("Этот трек уже есть в общем списке (дубликат).")
                    return

                await state.update_data(
                    candidate={
                        "spotify_id": track.spotify_id,
                        "name": track.name,
                        "artist": track.artist,
                        "url": track.url,
                    }
                )
                await state.set_state(_TrackStates.waiting_confirm)

                text = f"Нашёл трек:\n<b>{track.artist}</b> — <b>{track.name}</b>"
                if track.url:
                    text += f"\n{track.url}"
                text += "\n\nЭто тот трек?"
                await message.answer(text, reply_markup=_confirm_kb(track.spotify_id))

                _LOG.info(
                    "Candidate track prepared user_id=%s spotify_id=%s",
                    user_id,
                    track.spotify_id,
                )
            except Exception as e:
                _LOG.warning("Spotify lookup failed: %s", e)
                await message.answer("Ошибка при поиске Spotify. Попробуйте позже.")

        @router.message(Command("track"), F.chat.type == ChatType.PRIVATE)
        async def cmd_track(message: Message, state: FSMContext) -> None:
            _LOG.info(
                "Handling /track user_id=%s username=%s text=%r",
                getattr(message.from_user, "id", None),
                getattr(message.from_user, "username", None),
                message.text,
            )
            args = (message.text or "").split(maxsplit=1)
            if len(args) == 1:
                closed, close_ts = _is_closed(self._settings)
                if closed and close_ts is not None:
                    await message.answer(_closed_text(close_ts))
                    return
                await state.set_state(_TrackStates.waiting_query)
                await message.answer(
                    "Отправьте ссылку Spotify или название трека (можно с исполнителем)."
                )
                return
            await _handle_query(message, state, args[1])

        @router.callback_query(F.data == _TRACKS_MENU_CB)
        async def menu_add_track(cb: CallbackQuery, state: FSMContext) -> None:
            await cb.answer()
            closed, close_ts = _is_closed(self._settings)
            if closed and close_ts is not None:
                if cb.message:
                    await cb.message.answer(_closed_text(close_ts))
                return
            await state.set_state(_TrackStates.waiting_query)
            if cb.message:
                await cb.message.answer(
                    "Отправьте ссылку Spotify или название трека (можно с исполнителем)."
                )

        @router.message(_TrackStates.waiting_query, F.chat.type == ChatType.PRIVATE)
        async def got_query(message: Message, state: FSMContext) -> None:
            await _handle_query(message, state, message.text or "")

        @router.callback_query(F.data == "track:cancel")
        async def cancel(cb: CallbackQuery, state: FSMContext) -> None:
            await state.clear()
            await cb.answer("Отменено")
            if cb.message:
                await cb.message.answer("Ок, отменил. Чтобы добавить заново: /track")

        @router.callback_query(F.data.startswith("track:add:"))
        async def confirm_add(cb: CallbackQuery, state: FSMContext) -> None:
            if not cb.from_user or not cb.data:
                await cb.answer()
                return

            closed, close_ts = _is_closed(self._settings)
            if closed and close_ts is not None:
                await cb.answer("Закрыто", show_alert=True)
                if cb.message:
                    await cb.message.answer(_closed_text(close_ts))
                await state.clear()
                return

            data = await state.get_data()
            cand = (data or {}).get("candidate")
            if not cand:
                await cb.answer("Нет данных для добавления")
                return

            spotify_id = cb.data.split(":", 2)[2]
            if spotify_id != cand.get("spotify_id"):
                await cb.answer("Устаревшее подтверждение")
                return

            if self._tracks.exists_spotify_id(spotify_id):
                await cb.answer("Дубликат")
                if cb.message:
                    await cb.message.answer("Этот трек уже добавлен кем-то ранее (дубликат).")
                await state.clear()
                return

            max_tracks = _get_max_tracks_per_user(
                self._settings, fallback=self._max_tracks_per_user
            )
            if self._tracks.count_by_user(cb.from_user.id) >= max_tracks:
                await cb.answer("Лимит")
                if cb.message:
                    await cb.message.answer(
                        f"Лимит треков: {max_tracks}. Удалите один через /mytracks."
                    )
                await state.clear()
                return

            ok = self._tracks.add_track(
                spotify_id=spotify_id,
                name=cand.get("name") or "",
                artist=cand.get("artist") or "",
                url=cand.get("url"),
                added_by=cb.from_user.id,
            )
            await state.clear()
            if not ok:
                await cb.answer("Дубликат")
                if cb.message:
                    await cb.message.answer("Этот трек уже есть в списке (дубликат).")
                return

            await cb.answer("Добавлено")
            if cb.message:
                await cb.message.answer("Готово! Трек добавлен в общий список.")

        @router.message(Command("mytracks"), F.chat.type == ChatType.PRIVATE)
        async def mytracks(message: Message) -> None:
            _LOG.info(
                "Handling /mytracks user_id=%s username=%s",
                getattr(message.from_user, "id", None),
                getattr(message.from_user, "username", None),
            )
            if message.from_user is None:
                return
            limit = 20
            rows = self._tracks.list_by_user(message.from_user.id, limit=limit)
            if not rows:
                await message.answer("У вас пока нет добавленных треков. Добавить: /track")
                return
            await message.answer(f"Ваши треки (до {limit}): {len(rows)}")
            for r in rows:
                spotify_id, name, artist, url, added_at = (
                    r[0],
                    r[1],
                    r[2],
                    r[3],
                    r[4],
                )
                text = f"<b>{artist}</b> — <b>{name}</b>\n{url or ''}\nДобавлен: {added_at}"
                await message.answer(text, reply_markup=_delete_kb(spotify_id))

        @router.callback_query(F.data.startswith("track:del:"))
        async def delete_track(cb: CallbackQuery) -> None:
            if not cb.from_user or not cb.data:
                await cb.answer()
                return

            closed, close_ts = _is_closed(self._settings)
            if closed and close_ts is not None:
                await cb.answer("Закрыто", show_alert=True)
                if cb.message:
                    await cb.message.answer(_closed_text(close_ts))
                return

            spotify_id = cb.data.split(":", 2)[2]
            deleted = self._tracks.delete_by_user(cb.from_user.id, spotify_id)
            if deleted:
                await cb.answer("Удалено")
                if cb.message:
                    await cb.message.answer("Трек удалён.")
            else:
                await cb.answer("Не найден")
                if cb.message:
                    await cb.message.answer("Не нашёл этот трек среди ваших.")

    def register_admin(self, router: Router) -> None:
        @router.callback_query(F.data == _TRACKS_ADMIN_CB)
        async def admin_tracks(cb: CallbackQuery) -> None:
            await cb.answer()
            close_ts = _get_close_ts(self._settings)
            max_tracks = _get_max_tracks_per_user(
                self._settings, fallback=self._max_tracks_per_user
            )
            if close_ts is None:
                status = "Закрытие списка треков: не задано"
            else:
                status = _closed_text(close_ts)
            if cb.message:
                await cb.message.answer(
                    "Треки:\n"
                    f"{status}\n\n"
                    f"Лимит треков на пользователя: {max_tracks}\n\n"
                    "Команды:\n"
                    "- /tracks_close &lt;время&gt; (UTC) — задать закрытие\n"
                    "- /mytracks — ваши треки\n"
                    "- /track — добавить трек"
                )
