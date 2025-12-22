from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram.types import Message

from bot.plugins.system.tracks.plugin import _TrackStates


class ClearTracksWaitOnCommandMiddleware:
    """Clears Tracks plugin waiting states when user sends a command.

    This prevents the FSM from "hanging" in waiting_query/waiting_confirm if the
    user switches to another command (/mytracks, /start, etc.).
    """

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any],
    ) -> Any:
        try:
            text = getattr(event, "text", None)
            raw_state = data.get("raw_state")
            state = data.get("state")

            if (
                text
                and text.startswith("/")
                and raw_state in {
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
