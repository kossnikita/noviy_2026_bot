from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from bot.plugins.system.tracks.plugin import _TrackStates


class ClearTracksWaitOnCommandMiddleware(BaseMiddleware):
    """Clears Tracks plugin waiting states when user sends a command.

    This prevents the FSM from "hanging" in waiting_query/waiting_confirm if the
    user switches to another command (/mytracks, /start, etc.).
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        try:
            if isinstance(event, Message):
                text = getattr(event, "text", None)
                raw_state = data.get("raw_state")
                state = data.get("state")

                if (
                    text
                    and text.startswith("/")
                    and raw_state
                    in {
                        _TrackStates.waiting_query.state,
                        _TrackStates.waiting_confirm.state,
                    }
                    and state is not None
                ):
                    await state.clear()
        except Exception:
            # Never block message handling due to middleware issues
            pass

        return await handler(event, data)
