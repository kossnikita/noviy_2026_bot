import logging
from typing import Optional
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ChatType

from bot.db import UserRepo, ChatRepo, BlacklistRepo, SettingsRepo
from bot.plugins.loader import registry


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

    return router
