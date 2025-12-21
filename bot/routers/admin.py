import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from aiogram import Router, F
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.db import UserRepo, ChatRepo, BlacklistRepo, SettingsRepo
from bot.plugins.loader import registry


_TRACKS_CLOSE_TS_KEY = "tracks_close_at_ts"
_TRACKS_CLOSE_ANNOUNCED_FOR_TS_KEY = "tracks_close_announced_for_ts"


def _fmt_delta(seconds: int) -> str:
    seconds = max(0, int(seconds))
    minutes = seconds // 60
    hours = minutes // 60
    days = hours // 24
    minutes %= 60
    hours %= 24
    parts: list[str] = []
    if days:
        parts.append(f"{days}д")
    if hours:
        parts.append(f"{hours}ч")
    parts.append(f"{minutes}м")
    return " ".join(parts)


def _parse_close_time(arg: str, *, now_utc: datetime) -> datetime | None:
    raw = (arg or "").strip()
    if not raw:
        return None

    # Accept ISO-like strings.
    try:
        iso = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        pass

    # Accept: YYYY-MM-DD HH:MM
    try:
        dt = datetime.strptime(raw, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        pass

    # Accept: HH:MM (today; if already passed — next day)
    try:
        t = datetime.strptime(raw, "%H:%M").time()
        candidate = datetime(
            now_utc.year,
            now_utc.month,
            now_utc.day,
            t.hour,
            t.minute,
            tzinfo=timezone.utc,
        )
        if candidate <= now_utc:
            candidate = candidate + timedelta(days=1)
        return candidate
    except ValueError:
        return None


def _tracks_close_confirm_kb(close_ts: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить",
                    callback_data=f"tracks:close:confirm:{close_ts}",
                ),
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="tracks:close:cancel",
                ),
            ]
        ]
    )


def build_admin_menu_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=text, callback_data=cb)]
        for text, cb in registry.admin_menu_entries()
    ]
    if not rows:
        rows = [
            [
                InlineKeyboardButton(
                    text="Нет модулей админки", callback_data="noop"
                )
            ]
        ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def setup_admin_router(
    user_repo: UserRepo,
    chat_repo: ChatRepo,
    admin_id: int,
    blacklist_repo: Optional[BlacklistRepo] = None,
    settings_repo: Optional[SettingsRepo] = None,
) -> Router:
    router = Router(name="admin")
    logger = logging.getLogger("admin")

    def is_admin(message: Message) -> bool:
        return bool(message.from_user and message.from_user.id == admin_id)

    def _is_admin_cb(cb: CallbackQuery) -> bool:
        return bool(cb.from_user and cb.from_user.id == admin_id)

    @router.message(Command("admin"))
    async def admin_panel(message: Message):
        if not is_admin(message):
            return
        users = user_repo.count()
        groups = chat_repo.count()
        logger.info("Admin opened panel: users=%s groups=%s", users, groups)
        await message.answer(
            f"Админ панель\nПользователей: {users}\nГрупп: {groups}",
            reply_markup=build_admin_menu_keyboard(),
        )

    @router.message(
        Command("announce"),
        F.chat.type.in_(
            {ChatType.PRIVATE, ChatType.GROUP, ChatType.SUPERGROUP}
        ),
    )
    async def announce(message: Message):
        if not is_admin(message):
            return
        if not message.text:
            return
        if message.bot is None:
            return

        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            await message.reply("Использование: /announce текст")
            return
        text = parts[1]
        sent = 0
        for chat_id in chat_repo.group_chat_ids():
            try:
                await message.bot.send_message(chat_id, text)
                sent += 1
            except Exception:
                pass
        logger.info("Announce sent to %s chats", sent)
        await message.reply(f"Отправлено в {sent} чатов.")

    @router.message(Command("blacklist_add"))
    async def blacklist_add(message: Message):
        if not is_admin(message):
            return
        if not message.text:
            return
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            await message.reply(
                "Использование: /blacklist_add @username [примечание]"
            )
            return
        # support optional note separated by space after tag
        args = parts[1].split(maxsplit=1)
        tag = args[0]
        note = args[1] if len(args) > 1 else None
        if blacklist_repo:
            blacklist_repo.add(tag, note)
        updated = user_repo.blacklist_by_username(tag)
        logger.info("Blacklist add tag=%s updated_users=%s", tag, updated)
        await message.reply(
            f"Добавлено в чёрный список: {tag}. Обновлено записей пользователей: {updated}"
        )

    @router.message(Command("blacklist_remove"))
    async def blacklist_remove(message: Message):
        if not is_admin(message):
            return
        if not message.text:
            return
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            await message.reply("Использование: /blacklist_remove @username")
            return
        tag = parts[1].strip()
        if blacklist_repo:
            blacklist_repo.remove(tag)
        logger.info("Blacklist removed tag=%s", tag)
        await message.reply(f"Удалён из чёрного списка: {tag}")

    @router.message(Command("blacklist_list"))
    async def blacklist_list(message: Message):
        if not is_admin(message):
            return
        if not blacklist_repo:
            await message.reply("Репозиторий чёрного списка не доступен.")
            return
        items = list(blacklist_repo.list())
        if not items:
            await message.reply("Чёрный список пуст.")
            return
        lines = [f"@{t} - {n or ''} (added {c})" for t, n, c in items]
        logger.info("Blacklist listed: %s items", len(items))
        await message.reply("\n".join(lines))

    @router.message(Command("toggle_new_users"))
    async def toggle_new_users(message: Message):
        if not is_admin(message):
            return
        if not settings_repo:
            await message.reply("Репозиторий настроек недоступен.")
            return
        cur = settings_repo.get("allow_new_users", "1")
        new = "0" if cur == "1" else "1"
        settings_repo.set("allow_new_users", new)
        logger.info("Toggled allow_new_users to %s", new)
        await message.reply(
            "Автодобавление новых пользователей теперь: "
            f"{'включено' if new == '1' else 'выключено'}"
        )

    @router.message(Command("tracks_close"), F.chat.type == ChatType.PRIVATE)
    async def tracks_close(message: Message):
        if not is_admin(message):
            return
        if not settings_repo:
            await message.reply("Репозиторий настроек недоступен.")
            return
        if not message.text:
            return

        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            await message.reply(
                "Использование: /tracks_close <время>\n"
                "Форматы (UTC):\n"
                "- HH:MM\n"
                "- YYYY-MM-DD HH:MM\n"
                "- ISO: 2025-12-20T23:00:00Z"
            )
            return

        now_utc = datetime.now(timezone.utc)
        dt = _parse_close_time(parts[1], now_utc=now_utc)
        if dt is None:
            await message.reply("Не понял время. Пример: /tracks_close 23:00")
            return
        if dt <= now_utc:
            await message.reply("Время должно быть в будущем.")
            return

        close_ts = int(dt.timestamp())
        delta = int(close_ts - int(now_utc.timestamp()))
        await message.reply(
            "Подтвердите закрытие изменения треков:\n"
            f"Время (UTC): {dt:%Y-%m-%d %H:%M}\n"
            f"Наступит через: {_fmt_delta(delta)}",
            reply_markup=_tracks_close_confirm_kb(close_ts),
        )

    @router.callback_query(F.data == "tracks:close:cancel")
    async def tracks_close_cancel(cb: CallbackQuery):
        if not _is_admin_cb(cb):
            await cb.answer("Недостаточно прав", show_alert=True)
            return
        await cb.answer("Отменено")
        if cb.message:
            await cb.message.answer("Ок, отменил.")

    @router.callback_query(F.data.startswith("tracks:close:confirm:"))
    async def tracks_close_confirm(cb: CallbackQuery):
        if not _is_admin_cb(cb):
            await cb.answer("Недостаточно прав", show_alert=True)
            return
        if not settings_repo:
            await cb.answer("Настройки недоступны", show_alert=True)
            return
        data = cb.data or ""
        try:
            close_ts = int(data.split(":", 3)[3])
        except Exception:
            await cb.answer("Неверные данные", show_alert=True)
            return

        now_ts = int(datetime.now(timezone.utc).timestamp())
        if close_ts <= now_ts:
            await cb.answer("Это время уже прошло", show_alert=True)
            return

        settings_repo.set(_TRACKS_CLOSE_TS_KEY, str(close_ts))
        settings_repo.set(_TRACKS_CLOSE_ANNOUNCED_FOR_TS_KEY, "0")
        dt = datetime.fromtimestamp(close_ts, tz=timezone.utc)
        await cb.answer("Сохранено")
        if cb.message:
            await cb.message.answer(
                f"Готово. Изменение треков будет закрыто (UTC): {dt:%Y-%m-%d %H:%M}"
            )
        logger.info("Tracks close time set close_ts=%s by admin_id=%s", close_ts, admin_id)

    return router
