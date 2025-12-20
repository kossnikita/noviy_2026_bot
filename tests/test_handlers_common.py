import pytest

from aiogram import Dispatcher
from aiogram.enums import ChatType
from aiogram.methods import SendMessage
from aiogram.types import Update

from bot.db_sa import BlacklistRepo, SettingsRepo, UserRepo
from bot.routers.common import setup_common_router


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


@pytest.mark.asyncio
async def test_start_registers_new_user_when_allowed(db, bot_and_session, admin_id):
    bot, session = bot_and_session

    users = UserRepo(db)
    settings = SettingsRepo(db)
    blacklist = BlacklistRepo(db)

    router = setup_common_router(users, admin_id, settings, blacklist)
    dp = Dispatcher()
    dp.include_router(router)

    upd = _update_with_message(
        update_id=1,
        chat_id=100,
        user_id=200,
        text="/start",
        username="alice",
        chat_type=ChatType.PRIVATE.value,
    )

    await dp.feed_update(bot, upd)

    assert users.exists(200) is True
    # Should send welcome to user; admin notification may also be present.
    assert any(
        isinstance(r.method, SendMessage)
        and r.method.chat_id == 100
        and (r.method.text or "").startswith("Добро")
        for r in session.requests
    )


@pytest.mark.asyncio
async def test_start_rejects_new_user_when_disabled(db, bot_and_session, admin_id):
    bot, session = bot_and_session

    users = UserRepo(db)
    settings = SettingsRepo(db)
    blacklist = BlacklistRepo(db)

    settings.set("allow_new_users", "0")

    router = setup_common_router(users, admin_id, settings, blacklist)
    dp = Dispatcher()
    dp.include_router(router)

    upd = _update_with_message(
        update_id=2,
        chat_id=101,
        user_id=201,
        text="/start",
        username="bob",
        chat_type=ChatType.PRIVATE.value,
    )

    await dp.feed_update(bot, upd)

    assert users.exists(201) is False
    assert any(
        isinstance(r.method, SendMessage)
        and r.method.chat_id == 101
        and "Регистрация новых пользователей" in (r.method.text or "")
        for r in session.requests
    )


@pytest.mark.asyncio
async def test_start_blocks_blacklisted_user(db, bot_and_session, admin_id):
    bot, session = bot_and_session

    users = UserRepo(db)
    settings = SettingsRepo(db)
    blacklist = BlacklistRepo(db)

    blacklist.add("@badguy")

    router = setup_common_router(users, admin_id, settings, blacklist)
    dp = Dispatcher()
    dp.include_router(router)

    upd = _update_with_message(
        update_id=3,
        chat_id=102,
        user_id=202,
        text="/start",
        username="badguy",
        chat_type=ChatType.PRIVATE.value,
    )

    await dp.feed_update(bot, upd)

    assert users.exists(202) is True
    assert any(
        isinstance(r.method, SendMessage)
        and r.method.chat_id == 102
        and "отказано" in (r.method.text or "").lower()
        for r in session.requests
    )
