import logging
from aiogram import Router, F
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.enums import ChatType
from aiogram.fsm.state import default_state

from bot.api_repos import UserRepo, BlacklistRepo, SettingsRepo
from bot.plugins.loader import registry


def build_user_menu_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=text, callback_data=cb)]
        for text, cb in registry.user_menu_entries()
    ]
    if not buttons:
        buttons = [
            [
                InlineKeyboardButton(
                    text="Пока что пусто...", callback_data="noop"
                )
            ]
        ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def setup_common_router(
    user_repo: UserRepo,
    admin_id: int,
    settings_repo: SettingsRepo,
    blacklist_repo: BlacklistRepo,
) -> Router:
    router = Router(name="common")
    logger = logging.getLogger("common")

    # Activity is handled globally via ActivityMiddleware; no generic catch-all handler here

    @router.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
    async def on_start(message: Message):
        u = message.from_user
        if u is None:
            return

        bot = message.bot
        if bot is None:
            return

        is_new = not user_repo.exists(u.id)

        if is_new:
            # Check blacklist by username/tag
            if blacklist_repo.matches(u.username):
                user_repo.upsert_user(
                    u.id,
                    u.username,
                    u.first_name,
                    u.last_name,
                    is_admin=False,
                    is_blacklisted=True,
                )
                try:
                    await bot.send_message(
                        admin_id,
                        (
                            f"Черный список: пользователь @{u.username} ({u.id}) "
                            "попытался подключиться."
                        ),
                    )
                except Exception:
                    pass
                await message.answer("Вам отказано: вы в чёрном списке.")
                logger.info(
                    "Blocked blacklisted user: id=%s username=%s",
                    u.id,
                    u.username,
                )
                return

            allow = settings_repo.get("allow_new_users", "1") == "1"
            if allow:
                user_repo.upsert_user(
                    u.id,
                    u.username,
                    u.first_name,
                    u.last_name,
                    is_admin=False,
                    is_blacklisted=False,
                )
                try:
                    full = (u.first_name or "") + (
                        " " + u.last_name if u.last_name else ""
                    )
                    await bot.send_message(
                        admin_id,
                        f"Новый пользователь: @{u.username} ({u.id}) {full}",
                    )
                except Exception:
                    pass
                logger.info(
                    "New user registered: id=%s username=%s", u.id, u.username
                )
            else:
                try:
                    full = (u.first_name or "") + (
                        " " + u.last_name if u.last_name else ""
                    )
                    await bot.send_message(
                        admin_id,
                        (
                            "Новый пользователь попытался подключиться "
                            "(автодобавление отключено): "
                            f"@{u.username} ({u.id}) {full}"
                        ),
                    )
                except Exception:
                    pass
                await message.answer(
                    "Регистрация новых пользователей временно отключена."
                )
                logger.info(
                    "New user rejected (auto-add disabled): id=%s username=%s",
                    u.id,
                    u.username,
                )
                return
        else:
            logger.debug(
                "Existing user started bot: id=%s username=%s",
                u.id,
                u.username,
            )

        # mark activity for start interaction
        try:
            user_repo.touch_activity(u.id)
        except Exception:
            pass

        # existing or successfully added
        await message.answer("Добро пожаловать!")
        logger.debug("Sent welcome to user_id=%s", u.id)

    @router.message(Command("menu"), F.chat.type == ChatType.PRIVATE)
    async def menu(message: Message):
        try:
            if message.from_user:
                user_repo.touch_activity(message.from_user.id)
        except Exception:
            pass
        await message.answer(
            "Тут пока пусто.",
            reply_markup=build_user_menu_keyboard(),
        )
        logger.debug(
            "Menu requested by user_id=%s",
            getattr(message.from_user, "id", None),
        )

    @router.callback_query(F.data == "noop")
    async def noop_cb(cb: CallbackQuery):
        if cb.from_user:
            try:
                user_repo.touch_activity(cb.from_user.id)
            except Exception:
                pass
        await cb.answer("Скоро появятся конкурсы!", show_alert=False)
        logger.debug(
            "No-op callback by user_id=%s", getattr(cb.from_user, "id", None)
        )

    # Fallback: reply only when user is NOT in a dialog state and message is not a command
    @router.message(
        StateFilter(default_state),
        F.chat.type == ChatType.PRIVATE,
        F.text,
        ~F.text.startswith("/"),
    )
    async def fallback_text(message: Message):
        await message.answer(
            "Не понял сообщение.\n\n" "Команды: /menu, /track, /mytracks"
        )
        logger.debug(
            "Fallback text reply to user_id=%s",
            getattr(message.from_user, "id", None),
        )

    @router.message(
        StateFilter(default_state), F.chat.type == ChatType.PRIVATE, ~F.text
    )
    async def fallback_other(message: Message):
        # Non-text messages (stickers/photos/etc.)
        await message.answer("Я понимаю команды. Откройте меню: /menu")
        logger.debug(
            "Fallback non-text reply to user_id=%s",
            getattr(message.from_user, "id", None),
        )

    return router
