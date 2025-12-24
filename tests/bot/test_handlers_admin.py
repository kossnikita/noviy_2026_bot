import pytest

from aiogram import Dispatcher
from aiogram.enums import ChatType
from aiogram.methods import SendMessage
from aiogram.types import Update

from api.db_sa import BlacklistRepo, ChatRepo, SettingsRepo, UserRepo
from bot.routers.admin import setup_admin_router


def _update_with_message(
    *,
    update_id: int,
    chat_id: int,
    user_id: int,
    text: str,
    username: str = "admin",
    first_name: str = "Admin",
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
async def test_toggle_new_users_admin_only(db, bot_and_session, admin_id):
    bot, session = bot_and_session

    users = UserRepo(db)
    chats = ChatRepo(db)
    settings = SettingsRepo(db)
    blacklist = BlacklistRepo(db)

    router = setup_admin_router(users, chats, admin_id, blacklist, settings)
    dp = Dispatcher()
    dp.include_router(router)

    # Non-admin should be ignored
    upd = _update_with_message(
        update_id=10,
        chat_id=500,
        user_id=123,
        text="/toggle_new_users",
        chat_type=ChatType.PRIVATE.value,
    )
    await dp.feed_update(bot, upd)
    assert not any(
        isinstance(r.method, SendMessage) and r.method.chat_id == 500
        for r in session.requests
    )

    # Admin should toggle and receive a reply
    upd2 = _update_with_message(
        update_id=11,
        chat_id=501,
        user_id=admin_id,
        text="/toggle_new_users",
        chat_type=ChatType.PRIVATE.value,
    )
    await dp.feed_update(bot, upd2)

    assert settings.get("allow_new_users", "1") in {"0", "1"}
    assert any(
        isinstance(r.method, SendMessage)
        and r.method.chat_id == 501
        and "Автодобавление" in (r.method.text or "")
        for r in session.requests
    )
