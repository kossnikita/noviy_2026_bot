import logging

from aiogram import Router, F
from aiogram.enums import ChatType
from aiogram.filters import StateFilter
from aiogram.fsm.state import default_state
from aiogram.types import Message


def setup_unknown_commands_router() -> Router:
    router = Router(name="unknown_commands")
    logger = logging.getLogger("unknown_commands")

    @router.message(
        StateFilter(default_state),
        F.chat.type == ChatType.PRIVATE,
        F.text,
        F.text.startswith("/"),
    )
    async def unknown_command(message: Message):
        text = (message.text or "").strip()
        cmd = text.split(maxsplit=1)[0]
        logger.info(
            "Unknown command: %s user_id=%s username=%s",
            cmd,
            getattr(message.from_user, "id", None),
            getattr(message.from_user, "username", None),
        )
        await message.answer(
            "Неизвестная команда.\n"
            "Доступно: /menu, /track, /mytracks"
        )

    logger.info("Unknown-command handler registered")
    return router
