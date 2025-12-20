import logging
from typing import Any, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message


class CommandLoggingMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        super().__init__()
        self._log = logging.getLogger("commands")

    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Any],
        event: Any,
        data: Dict[str, Any],
    ) -> Any:
        if isinstance(event, Message):
            text = (event.text or "").strip()
            if text.startswith("/"):
                first = text.split(maxsplit=1)[0]
                cmd = first[1:]
                # Handle /cmd@BotName
                if "@" in cmd:
                    cmd = cmd.split("@", 1)[0]

                self._log.info(
                    "Command invoked: /%s chat_id=%s chat_type=%s user_id=%s username=%s text=%r",
                    cmd,
                    getattr(event.chat, "id", None),
                    getattr(event.chat, "type", None),
                    getattr(event.from_user, "id", None),
                    getattr(event.from_user, "username", None),
                    text,
                )

        return await handler(event, data)
