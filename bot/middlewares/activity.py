import logging
from typing import Callable, Any, Dict

from aiogram.types import Message, CallbackQuery
from aiogram import BaseMiddleware

from bot.db import UserRepo


class ActivityMiddleware(BaseMiddleware):
    def __init__(self, user_repo: UserRepo):
        super().__init__()
        self.user_repo = user_repo
        self._log = logging.getLogger(self.__class__.__name__)

    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Any],
        event: Any,
        data: Dict[str, Any],
    ) -> Any:
        try:
            user_id = None
            if isinstance(event, Message):
                if event.from_user:
                    user_id = event.from_user.id
            elif isinstance(event, CallbackQuery):
                if event.from_user:
                    user_id = event.from_user.id

            if user_id is not None:
                self.user_repo.touch_activity(user_id)
                self._log.debug("Activity touched via middleware for user_id=%s", user_id)
        except Exception:
            # Avoid breaking handler chain on DB errors
            pass

        return await handler(event, data)
