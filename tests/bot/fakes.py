from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncGenerator, List, Optional

from aiogram.client.session.base import BaseSession
from aiogram.methods.base import TelegramMethod
from aiogram.types import Message


@dataclass
class CapturedRequest:
    api_method: str
    method: TelegramMethod[Any]


class FakeSession(BaseSession):
    """A minimal aiogram session that never hits Telegram.

    It captures outgoing API method calls (sendMessage, setMyCommands, etc.)
    and returns minimal valid objects expected by aiogram.
    """

    def __init__(self):
        super().__init__()
        self.requests: List[CapturedRequest] = []

    async def close(self) -> None:
        return None

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes, None]:
        _ = (url, headers, timeout, chunk_size, raise_for_status)
        # This method isn't used in our tests; keep it as a valid async generator.
        if False:  # pragma: no cover
            yield b""
        raise NotImplementedError("stream_content is not used in tests")

    async def make_request(
        self,
        bot: Any,
        method: TelegramMethod[Any],
        timeout: Optional[int] = None,
    ) -> Any:
        api = getattr(method, "__api_method__", method.__class__.__name__)
        self.requests.append(CapturedRequest(api_method=api, method=method))

        if api == "sendMessage":
            payload = method.model_dump()
            chat_id = payload["chat_id"]
            text = payload.get("text")
            # Telegram API returns an integer unix timestamp for `date`.
            msg = {
                "message_id": len(self.requests),
                "date": 0,
                "chat": {"id": chat_id, "type": "private"},
                "text": text,
            }
            return Message.model_validate(msg)

        if api == "sendPhoto":
            payload = method.model_dump()
            chat_id = payload["chat_id"]
            # Telegram API returns an integer unix timestamp for `date`.
            msg = {
                "message_id": len(self.requests),
                "date": 0,
                "chat": {"id": chat_id, "type": "private"},
            }
            return Message.model_validate(msg)

        # Most bot setup calls return boolean in Telegram API.
        if api in {
            "setMyCommands",
            "deleteMessage",
            "editMessageText",
            "answerCallbackQuery",
        }:
            return True

        # Default fallback: return True for methods we don't care about.
        return True
