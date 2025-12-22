import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

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
from bot.plugins.system.tracks.tracks_closure import (
    run_tracks_closure_scheduler,
)


_LOG = logging.getLogger("tracks")

_TRACKS_CLOSE_TS_KEY = "tracks_close_at_ts"
_MAX_TRACKS_PER_USER_KEY = "max_tracks_per_user"
_TRACKS_ADMIN_CB = "tracks:admin"
_TRACKS_MENU_CB = "tracks:menu"

_WAIT_QUERY_TIMEOUT_S = 180
_WAIT_CONFIRM_TIMEOUT_S = 180


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
    return (
        "Список треков закрыт для изменений.\n"
        f"Время закрытия (UTC): {dt:%Y-%m-%d %H:%M}"
    )


def _get_max_tracks_per_user(settings: SettingsRepo, *, fallback: int) -> int:
    raw = (settings.get(_MAX_TRACKS_PER_USER_KEY, "") or "").strip()
    try:
        v = int(raw)
        if v >= 0:
            # 0 means "no per-user limit"
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
                InlineKeyboardButton(
                    text="❌ Нет", callback_data="track:cancel"
                ),
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
        self._spotify = SpotifyClient(
            cfg.spotify_client_id, cfg.spotify_client_secret
        )
        self._max_tracks_per_user = int(cfg.max_tracks_per_user)
        self._admin_id = int(cfg.admin_id)

        self._scheduler_task: asyncio.Task[None] | None = None

        self._state_timeout_tasks: dict[tuple[int, int], asyncio.Task[None]] = {}

    def _cancel_state_timeout(self, key: tuple[int, int]) -> None:
        t = self._state_timeout_tasks.pop(key, None)
        if t is not None:
            t.cancel()

    def _arm_state_timeout(
        self,
        *,
        key: tuple[int, int],
        state: FSMContext,
        expected_state: str,
        timeout_s: int,
    ) -> None:
        self._cancel_state_timeout(key)

        async def _job() -> None:
            try:
                await asyncio.sleep(timeout_s)
                cur = await state.get_state()
                if cur == expected_state:
                    await state.clear()
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOG.exception("State timeout job failed")
            finally:
                if self._state_timeout_tasks.get(key) is task:
                    self._state_timeout_tasks.pop(key, None)

        task = asyncio.create_task(_job())
        self._state_timeout_tasks[key] = task

    def start(self, bot: Bot) -> asyncio.Task[None] | None:
        if (
            self._scheduler_task is not None
            and not self._scheduler_task.done()
        ):
            return self._scheduler_task

        self._scheduler_task = asyncio.create_task(
            run_tracks_closure_scheduler(bot, self._settings, self._chats)
        )
        return self._scheduler_task

    def register_user(self, router: Router) -> None:
        _LOG.info("Tracks plugin registered: /track /mytracks")

        async def _handle_query(
            message: Message, state: FSMContext, query: str
        ) -> None:
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
                _LOG.error("Spotify client not configured")
                await message.answer(
                    "Spotify не настроен. Сообщите администратору."
                )
                return

            if message.from_user is None:
                return

            user_id = message.from_user.id
            max_tracks = _get_max_tracks_per_user(
                self._settings, fallback=self._max_tracks_per_user
            )
            if (
                max_tracks != 0
                and self._tracks.count_by_user(user_id) >= max_tracks
            ):
                _LOG.debug(
                    "User %s reached max tracks limit %s", user_id, max_tracks
                )
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
                    await message.answer(
                        "Этот трек уже кто-то добавил. Попробуй другой."
                    )
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

                try:
                    key = (message.chat.id, user_id)
                    self._arm_state_timeout(
                        key=key,
                        state=state,
                        expected_state=_TrackStates.waiting_confirm.state,
                        timeout_s=_WAIT_CONFIRM_TIMEOUT_S,
                    )
                except Exception:
                    _LOG.exception("Failed to arm confirm timeout")

                text = (
                    f"Нашёл трек:\n<b>{track.artist}</b> — <b>{track.name}</b>"
                )
                if track.url:
                    text += f"\n{track.url}"
                text += "\n\nЭто тот трек?"
                await message.answer(
                    text, reply_markup=_confirm_kb(track.spotify_id)
                )

                _LOG.info(
                    "Candidate track prepared user_id=%s spotify_id=%s",
                    user_id,
                    track.spotify_id,
                )
            except Exception as e:
                _LOG.warning("Spotify lookup failed: %s", e)
                await message.answer(
                    "Ошибка при поиске Spotify. Попробуйте позже."
                )

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
                # No query provided yet
                closed, close_ts = _is_closed(self._settings)
                if closed and close_ts is not None:
                    await message.answer(_closed_text(close_ts))
                    return
                await state.set_state(_TrackStates.waiting_query)
                if message.from_user is not None:
                    self._arm_state_timeout(
                        key=(message.chat.id, message.from_user.id),
                        state=state,
                        expected_state=_TrackStates.waiting_query.state,
                        timeout_s=_WAIT_QUERY_TIMEOUT_S,
                    )
                await message.answer(
                    "Отправьте ссылку Spotify или название трека (можно с исполнителем)."
                )
                return
            # Query provided as command argument
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
            if cb.message and cb.from_user:
                self._arm_state_timeout(
                    key=(cb.message.chat.id, cb.from_user.id),
                    state=state,
                    expected_state=_TrackStates.waiting_query.state,
                    timeout_s=_WAIT_QUERY_TIMEOUT_S,
                )
            if cb.message:
                await cb.message.answer(
                    "Отправьте ссылку Spotify или название трека (можно с исполнителем)."
                )

        @router.message(
            _TrackStates.waiting_query,
            F.chat.type == ChatType.PRIVATE,
            F.text,
            F.text.startswith("/"),
        )
        async def command_while_waiting_query(
            message: Message, state: FSMContext
        ) -> None:
            if message.from_user is None:
                raise SkipHandler
            self._cancel_state_timeout((message.chat.id, message.from_user.id))
            await state.clear()
            raise SkipHandler

        @router.message(
            _TrackStates.waiting_confirm,
            F.chat.type == ChatType.PRIVATE,
            F.text,
            F.text.startswith("/"),
        )
        async def command_while_waiting_confirm(
            message: Message, state: FSMContext
        ) -> None:
            if message.from_user is None:
                raise SkipHandler
            self._cancel_state_timeout((message.chat.id, message.from_user.id))
            await state.clear()
            raise SkipHandler

        @router.message(
            _TrackStates.waiting_query,
            F.chat.type == ChatType.PRIVATE,
            F.text,
            ~F.text.startswith("/"),
        )
        async def got_query(message: Message, state: FSMContext) -> None:
            if message.from_user is not None:
                self._cancel_state_timeout((message.chat.id, message.from_user.id))
            await _handle_query(message, state, message.text or "")

        @router.callback_query(F.data == "track:cancel")
        async def cancel(cb: CallbackQuery, state: FSMContext) -> None:
            if cb.message and cb.from_user:
                self._cancel_state_timeout((cb.message.chat.id, cb.from_user.id))
            await state.clear()
            await cb.answer("Отменено")
            if cb.message:
                await cb.message.answer(
                    "Ок, отменил. Чтобы добавить заново: /track"
                )

        @router.callback_query(F.data.startswith("track:add:"))
        async def confirm_add(cb: CallbackQuery, state: FSMContext) -> None:
            if not cb.from_user or not cb.data:
                await cb.answer()
                return

            if cb.message:
                self._cancel_state_timeout((cb.message.chat.id, cb.from_user.id))

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

            if self._tracks.exists_spotify_id(spotify_id=spotify_id):
                await cb.answer("Уже добавлен")
                if cb.message:
                    await cb.message.answer("Этот трек уже добавлен кем-то.")
                await state.clear()
                return

            max_tracks = _get_max_tracks_per_user(
                self._settings, fallback=self._max_tracks_per_user
            )
            if (
                max_tracks != 0
                and self._tracks.count_by_user(cb.from_user.id) >= max_tracks
            ):
                await cb.answer("Лимит")
                if cb.message:
                    await cb.message.answer(
                        f"Лимит треков: {max_tracks}. Удалите трек через /mytracks."
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
                await cb.answer("Уже добавлен")
                if cb.message:
                    await cb.message.answer("Этот трек уже добавлен кем-то.")
                return

            await cb.answer("Добавлено")
            if cb.message:
                await cb.message.answer(
                    "Готово! Трек добавлен в общий список."
                )

        @router.message(Command("mytracks"), F.chat.type == ChatType.PRIVATE)
        async def mytracks(message: Message) -> None:
            _LOG.info(
                "Handling /mytracks user_id=%s username=%s",
                getattr(message.from_user, "id", None),
                getattr(message.from_user, "username", None),
            )
            if message.from_user is None:
                return
            max_tracks = _get_max_tracks_per_user(
                self._settings, fallback=self._max_tracks_per_user
            )

            list_limit = 50 if max_tracks == 0 else max_tracks
            rows = self._tracks.list_by_user(
                message.from_user.id, limit=list_limit
            )
            if not rows:
                await message.answer(
                    "У вас пока нет добавленных треков. Добавить: /track"
                )
                return
            if max_tracks == 0:
                await message.answer(f"Ваши треки: {len(rows)}")
            else:
                await message.answer(
                    f"Ваши треки (лимит: {max_tracks}): {len(rows)}"
                )
            for r in rows:
                spotify_id, name, artist, url = (
                    r[0],
                    r[1],
                    r[2],
                    r[3],
                )
                text = f"<b>{artist}</b> — <b>{name}</b>\n{url or ''}\n"
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
        @router.message(
            Command("tracks_limit"), F.chat.type == ChatType.PRIVATE
        )
        async def tracks_limit(message: Message) -> None:
            if not message.from_user or message.from_user.id != self._admin_id:
                return
            if not message.text:
                return

            parts = message.text.split(maxsplit=1)
            if len(parts) < 2:
                raw = (
                    self._settings.get(_MAX_TRACKS_PER_USER_KEY, "") or ""
                ).strip()
                if raw == "0":
                    cur = "без ограничений"
                elif raw:
                    cur = raw
                else:
                    cur = str(self._max_tracks_per_user)
                await message.answer(
                    "Использование: /tracks_limit &lt;число&gt;\n"
                    "0 — без ограничений на пользователя\n\n"
                    f"Текущее значение: {cur}"
                )
                return

            raw = parts[1].strip()
            try:
                n = int(raw)
            except Exception:
                await message.answer("Не понял число. Пример: /tracks_limit 5")
                return
            if n < 0:
                await message.answer("Значение не может быть отрицательным.")
                return

            self._settings.set(_MAX_TRACKS_PER_USER_KEY, str(n))
            if n == 0:
                await message.answer(
                    "Готово. Теперь лимита треков на пользователя нет."
                )
            else:
                await message.answer(
                    f"Готово. Лимит треков на пользователя: {n}"
                )
            _LOG.info(
                "Tracks limit set to %s by admin_id=%s", n, self._admin_id
            )

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
                limit_text = (
                    "без ограничений" if max_tracks == 0 else str(max_tracks)
                )
                await cb.message.answer(
                    "Треки:\n"
                    f"{status}\n\n"
                    f"Лимит треков на пользователя: {limit_text}\n\n"
                    "Команды:\n"
                    "- /tracks_close &lt;время&gt; (UTC) — задать закрытие\n"
                    "- /tracks_limit &lt;число&gt; — лимит (0 = без ограничений)\n"
                    "- /mytracks — ваши треки\n"
                    "- /track — добавить трек"
                )
