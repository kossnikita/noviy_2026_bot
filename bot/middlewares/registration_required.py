import logging
from typing import Any, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, Message

from bot.db import UserRepo


class RegistrationRequiredMiddleware(BaseMiddleware):
    def __init__(self, user_repo: UserRepo):
        super().__init__()
        self.user_repo = user_repo
        self._log = logging.getLogger("registration")

    def _is_allowed_message(self, message: Message) -> bool:
        text = (message.text or "").strip()
        if not text:
            return True
        # Allow /start even if not registered.
        if text.startswith("/start"):
            return True
        return False

    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Any],
        event: Any,
        data: Dict[str, Any],
    ) -> Any:
        if isinstance(event, Message):
            if getattr(event.chat, "type", None) == ChatType.PRIVATE:
                if event.from_user and not self._is_allowed_message(event):
                    user_id = event.from_user.id
                    if not self.user_repo.exists(user_id):
                        self._log.info(
                            "Blocked message from unregistered user_id=%s text=%r",
                            user_id,
                            (event.text or ""),
                        )
                        await event.answer(
                            "Сначала зарегистрируйтесь командой /start."
                        )
                        return None

        if isinstance(event, CallbackQuery):
            msg = event.message
            if msg is not None and getattr(msg.chat, "type", None) == ChatType.PRIVATE:
                if event.from_user:
                    user_id = event.from_user.id
                    if not self.user_repo.exists(user_id):
                        self._log.info(
                            "Blocked callback from unregistered user_id=%s data=%r",
                            user_id,
                            getattr(event, "data", None),
                        )
                        try:
                            await event.answer(
                                "Сначала зарегистрируйтесь командой /start.",
                                show_alert=True,
                            )
                        except Exception:
                            pass
                        return None

        return await handler(event, data)
