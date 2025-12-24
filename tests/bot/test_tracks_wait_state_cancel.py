import pytest

from aiogram import Dispatcher
from aiogram.enums import ChatType
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.base import StorageKey
from aiogram.filters import Command
from aiogram.methods import SendMessage
from aiogram import Router
from aiogram.types import Update

from bot.middlewares.clear_tracks_wait_on_command import (
    ClearTracksWaitOnCommandMiddleware,
)
from bot.plugins.system.tracks.plugin import _TrackStates


def _update_with_message(
    *,
    update_id: int,
    chat_id: int,
    user_id: int,
    text: str,
    username: str = "alice",
    first_name: str = "Alice",
    chat_type: str = "private",
) -> Update:
    payload = {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "date": 0,
            "chat": {"id": chat_id, "type": chat_type},
            "from": {
                "id": user_id,
                "is_bot": False,
                "first_name": first_name,
                "username": username,
            },
            "text": text,
        },
    }
    return Update.model_validate(payload)


async def _set_state(
    *, dp: Dispatcher, bot_id: int, chat_id: int, user_id: int, state: str
) -> None:
    key = StorageKey(bot_id=bot_id, chat_id=chat_id, user_id=user_id)
    await dp.storage.set_state(key=key, state=state)


async def _get_state(
    *, dp: Dispatcher, bot_id: int, chat_id: int, user_id: int
) -> str | None:
    key = StorageKey(bot_id=bot_id, chat_id=chat_id, user_id=user_id)
    return await dp.storage.get_state(key=key)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "initial_state",
    [_TrackStates.waiting_query.state, _TrackStates.waiting_confirm.state],
)
async def test_command_clears_tracks_wait_state_and_allows_command_handler(
    bot_and_session, initial_state
):
    bot, session = bot_and_session

    dp = Dispatcher(storage=MemoryStorage())
    dp.message.middleware(ClearTracksWaitOnCommandMiddleware())

    router = Router()

    @router.message(Command("mytracks"))
    async def mytracks_handler(message):
        await message.answer("MYTRACKS_OK")

    dp.include_router(router)

    chat_id = 100
    user_id = 200

    await _set_state(
        dp=dp,
        bot_id=bot.id,
        chat_id=chat_id,
        user_id=user_id,
        state=initial_state,
    )

    upd = _update_with_message(
        update_id=1,
        chat_id=chat_id,
        user_id=user_id,
        text="/mytracks",
        chat_type=ChatType.PRIVATE.value,
    )

    await dp.feed_update(bot, upd)

    assert (
        await _get_state(
            dp=dp, bot_id=bot.id, chat_id=chat_id, user_id=user_id
        )
    ) is None

    assert any(
        isinstance(r.method, SendMessage)
        and r.method.chat_id == chat_id
        and (r.method.text or "") == "MYTRACKS_OK"
        for r in session.requests
    )


@pytest.mark.asyncio
async def test_non_command_does_not_clear_tracks_wait_state(bot_and_session):
    bot, _session = bot_and_session

    dp = Dispatcher(storage=MemoryStorage())
    dp.message.middleware(ClearTracksWaitOnCommandMiddleware())

    router = Router()

    @router.message()
    async def any_text(_message):
        # Do nothing; we only care about state preservation
        return None

    dp.include_router(router)

    chat_id = 101
    user_id = 201

    await _set_state(
        dp=dp,
        bot_id=bot.id,
        chat_id=chat_id,
        user_id=user_id,
        state=_TrackStates.waiting_query.state,
    )

    upd = _update_with_message(
        update_id=2,
        chat_id=chat_id,
        user_id=user_id,
        text="some query",
        chat_type=ChatType.PRIVATE.value,
    )

    await dp.feed_update(bot, upd)

    assert (
        await _get_state(
            dp=dp, bot_id=bot.id, chat_id=chat_id, user_id=user_id
        )
    ) == _TrackStates.waiting_query.state


@pytest.mark.asyncio
async def test_command_does_not_clear_unrelated_state(bot_and_session):
    bot, _session = bot_and_session

    dp = Dispatcher(storage=MemoryStorage())
    dp.message.middleware(ClearTracksWaitOnCommandMiddleware())

    router = Router()

    @router.message(Command("start"))
    async def start_handler(_message):
        return None

    dp.include_router(router)

    chat_id = 102
    user_id = 202

    await _set_state(
        dp=dp,
        bot_id=bot.id,
        chat_id=chat_id,
        user_id=user_id,
        state="some:other_state",
    )

    upd = _update_with_message(
        update_id=3,
        chat_id=chat_id,
        user_id=user_id,
        text="/start",
        chat_type=ChatType.PRIVATE.value,
    )

    await dp.feed_update(bot, upd)

    assert (
        await _get_state(
            dp=dp, bot_id=bot.id, chat_id=chat_id, user_id=user_id
        )
    ) == "some:other_state"
