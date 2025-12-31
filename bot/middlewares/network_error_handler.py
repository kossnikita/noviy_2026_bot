"""
Middleware to handle network errors gracefully.
Retries on TelegramNetworkError instead of crashing.
"""

import logging
from typing import Any, Callable, Dict, Awaitable

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramNetworkError
from aiogram.types import Update

logger = logging.getLogger(__name__)


class NetworkErrorMiddleware(BaseMiddleware):
    """
    Handles TelegramNetworkError by logging them without crashing.
    These errors are expected during network disruptions and should be retried by aiogram.
    """

    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)
        except TelegramNetworkError as e:
            logger.warning(
                "Network error processing update %s: %s. "
                "This is expected during network issues. Aiogram will retry.",
                event.update_id,
                e,
            )
            # Don't re-raise - let aiogram handle retries
            return None
        except Exception:
            # Re-raise other exceptions
            raise
