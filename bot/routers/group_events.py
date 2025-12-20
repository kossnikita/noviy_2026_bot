import logging
from aiogram import Router, F
from aiogram.types import Message
from aiogram.types import ChatMemberUpdated
from aiogram.enums import ChatType

from bot.db import ChatRepo, UserRepo


def setup_group_router(chat_repo: ChatRepo, user_repo: UserRepo) -> Router:
    router = Router(name="group")
    logger = logging.getLogger("group")

    @router.chat_member()
    async def on_chat_member(update: ChatMemberUpdated):
        chat = update.chat
        if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
            chat_repo.upsert_chat(
                chat.id,
                str(chat.type),
                chat.title,
            )
            logger.info(
                "Known group updated: id=%s title=%s",
                chat.id,
                getattr(chat, "title", None),
            )

    @router.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
    async def on_group_message(msg: Message):
        chat = msg.chat
        chat_repo.upsert_chat(
            chat.id,
            str(chat.type),
            chat.title,
        )
        logger.debug(
            "Group message in chat_id=%s by user_id=%s",
            chat.id,
            getattr(msg.from_user, "id", None),
        )
        # Record user activity when users post in groups
        if msg.from_user:
            try:
                user_repo.touch_activity(msg.from_user.id)
            except Exception:
                pass

    return router
