import logging

from aiogram import Router, F
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from bot.db import SpotifyTracksRepo
from bot.integrations.spotify_client import SpotifyClient


class TrackStates(StatesGroup):
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


def setup_tracks_router(
    tracks_repo: SpotifyTracksRepo,
    spotify: SpotifyClient,
    max_tracks_per_user: int,
) -> Router:
    router = Router(name="tracks")
    logger = logging.getLogger("tracks")

    logger.info("Tracks commands registered: /track /mytracks")

    async def _handle_query(message: Message, state: FSMContext, query: str):
        if not spotify.is_configured():
            await message.answer(
                "Spotify не настроен. Нужны SPOTIFY_CLIENT_ID и SPOTIFY_CLIENT_SECRET."
            )
            return

        if message.from_user is None:
            return

        user_id = message.from_user.id
        if tracks_repo.count_by_user(user_id) >= max_tracks_per_user:
            await message.answer(
                f"Лимит треков: {max_tracks_per_user}. "
                "Сначала удалите один из своих треков через /mytracks."
            )
            return

        try:
            spotify_id = SpotifyClient.parse_spotify_track_id(query)
            if spotify_id:
                track = spotify.get_track(spotify_id)
            else:
                track = spotify.search_track(query)
                if not track:
                    await message.answer(
                        "Не смог найти трек в Spotify. "
                        "Попробуйте ссылку или более точный запрос."
                    )
                    return

            if tracks_repo.exists_spotify_id(track.spotify_id):
                await message.answer(
                    "Этот трек уже есть в общем списке (дубликат)."
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
            await state.set_state(TrackStates.waiting_confirm)

            text = f"Нашёл трек:\n<b>{track.artist}</b> — <b>{track.name}</b>"
            if track.url:
                text += f"\n{track.url}"
            text += "\n\nЭто тот трек?"
            await message.answer(
                text, reply_markup=_confirm_kb(track.spotify_id)
            )
            logger.info(
                "Candidate track prepared user_id=%s spotify_id=%s",
                user_id,
                track.spotify_id,
            )
        except Exception as e:
            logger.warning("Spotify lookup failed: %s", e)
            await message.answer(
                "Ошибка при поиске Spotify. Попробуйте позже."
            )

    @router.message(Command("track"), F.chat.type == ChatType.PRIVATE)
    async def cmd_track(message: Message, state: FSMContext):
        logger.info(
            "Handling /track user_id=%s username=%s text=%r",
            getattr(message.from_user, "id", None),
            getattr(message.from_user, "username", None),
            message.text,
        )
        args = (message.text or "").split(maxsplit=1)
        if len(args) == 1:
            await state.set_state(TrackStates.waiting_query)
            await message.answer(
                "Отправьте ссылку Spotify или название трека (можно с исполнителем)."
            )
            return
        await _handle_query(message, state, args[1])

    @router.message(TrackStates.waiting_query, F.chat.type == ChatType.PRIVATE)
    async def got_query(message: Message, state: FSMContext):
        await _handle_query(message, state, message.text or "")

    @router.callback_query(F.data == "track:cancel")
    async def cancel(cb: CallbackQuery, state: FSMContext):
        await state.clear()
        await cb.answer("Отменено")
        if cb.message:
            await cb.message.answer(
                "Ок, отменил. Чтобы добавить заново: /track"
            )

    @router.callback_query(F.data.startswith("track:add:"))
    async def confirm_add(cb: CallbackQuery, state: FSMContext):
        if not cb.from_user:
            await cb.answer()
            return
        if not cb.data:
            await cb.answer()
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

        if tracks_repo.exists_spotify_id(spotify_id):
            await cb.answer("Дубликат")
            if cb.message:
                await cb.message.answer(
                    "Этот трек уже добавлен кем-то ранее (дубликат)."
                )
            await state.clear()
            return

        if tracks_repo.count_by_user(cb.from_user.id) >= max_tracks_per_user:
            await cb.answer("Лимит")
            if cb.message:
                await cb.message.answer(
                    f"Лимит треков: {max_tracks_per_user}. Удалите один через /mytracks."
                )
            await state.clear()
            return

        ok = tracks_repo.add_track(
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
                await cb.message.answer(
                    "Этот трек уже есть в списке (дубликат)."
                )
            return

        await cb.answer("Добавлено")
        if cb.message:
            await cb.message.answer("Готово! Трек добавлен в общий список.")

    @router.message(Command("mytracks"), F.chat.type == ChatType.PRIVATE)
    async def mytracks(message: Message):
        logger.info(
            "Handling /mytracks user_id=%s username=%s",
            getattr(message.from_user, "id", None),
            getattr(message.from_user, "username", None),
        )
        if message.from_user is None:
            return
        rows = tracks_repo.list_by_user(message.from_user.id, limit=20)
        if not rows:
            await message.answer(
                "У вас пока нет добавленных треков. Добавить: /track"
            )
            return

        await message.answer(f"Ваши треки (до 20): {len(rows)}")
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
    async def delete_track(cb: CallbackQuery):
        if not cb.from_user:
            await cb.answer()
            return
        if not cb.data:
            await cb.answer()
            return
        spotify_id = cb.data.split(":", 2)[2]
        deleted = tracks_repo.delete_by_user(cb.from_user.id, spotify_id)
        if deleted:
            await cb.answer("Удалено")
            if cb.message:
                await cb.message.answer("Трек удалён.")
        else:
            await cb.answer("Не найден")
            if cb.message:
                await cb.message.answer("Не нашёл этот трек среди ваших.")

    return router
