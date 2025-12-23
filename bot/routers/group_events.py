import logging
from aiogram import Router, F
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.types import Message
from aiogram.types import ChatMemberUpdated
from aiogram.enums import ChatType

from bot.api_repos import ChatRepo, UserRepo


def setup_group_router(chat_repo: ChatRepo, user_repo: UserRepo) -> Router:
    router = Router(name="group")
    logger = logging.getLogger("group")
    logger.info("Group router initialized")

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
            "Group message: chat_id=%s type=%s msg_id=%s user_id=%s has_text=%s has_photo=%s",
            getattr(chat, "id", None),
            getattr(chat, "type", None),
            getattr(msg, "message_id", None),
            getattr(getattr(msg, "from_user", None), "id", None),
            bool(getattr(msg, "text", None)),
            bool(getattr(msg, "photo", None)),
        )
        # Record user activity when users post in groups
        if msg.from_user:
            try:
                user_repo.touch_activity(msg.from_user.id)
            except Exception:
                pass

        # Do not consume the update: allow plugins (e.g., photo saver) to handle it.
        raise SkipHandler()

    return router
