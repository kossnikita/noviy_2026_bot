import pytest

from types import SimpleNamespace
from aiogram import Dispatcher
from aiogram.methods import SendMessage
from aiogram.types import Update
from aiogram.enums import ChatType

from bot.plugins.system.player.plugin import Plugin
from bot.routers.admin import setup_admin_router
from api.db_sa import UserRepo, ChatRepo, SettingsRepo, BlacklistRepo


def _update_with_message(*, update_id: int, chat_id: int, user_id: int, text: str, username: str = "admin") -> Update:
    payload = {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "date": 0,
            "chat": {"id": chat_id, "type": ChatType.PRIVATE.value},
            "from": {"id": user_id, "is_bot": False, "first_name": username, "username": username},
            "text": text,
        },
    }
    return Update.model_validate(payload)


def _update_with_callback(*, update_id: int, chat_id: int, user_id: int, data: str) -> Update:
    payload = {
        "update_id": update_id,
        "callback_query": {
            "id": str(update_id),
            "from": {"id": user_id, "is_bot": False, "first_name": "admin", "username": "admin"},
            "message": {"message_id": update_id, "date": 0, "chat": {"id": chat_id, "type": ChatType.PRIVATE.value}},
            "chat_instance": "",
            "data": data,
        },
    }
    return Update.model_validate(payload)


@pytest.mark.asyncio
async def test_admin_button_and_command(db, bot_and_session, admin_id):
    bot, session = bot_and_session

    users = UserRepo(db)
    chats = ChatRepo(db)
    settings = SettingsRepo(db)
    blacklist = BlacklistRepo(db)

    plugin = Plugin()

    # admin menu button present
    btn = plugin.admin_menu_button()
    assert isinstance(btn, tuple) and btn[1] == "player:admin"

    # keyboard helper builds markup
    kb = plugin.keyboard()
    assert hasattr(kb, "inline_keyboard") and len(kb.inline_keyboard) >= 2


@pytest.mark.asyncio
async def test_admin_callback_shows_panel(db, bot_and_session, admin_id):
    bot, session = bot_and_session

    users = UserRepo(db)
    chats = ChatRepo(db)
    settings = SettingsRepo(db)
    blacklist = BlacklistRepo(db)

    plugin = Plugin()
    kb = plugin.keyboard()
    # keyboard contains expected callback_data strings
    flat = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "player:cmd:play" in flat and "player:cmd:pause" in flat


@pytest.mark.asyncio
async def test_handle_cmd_calls_api(db, bot_and_session, admin_id, monkeypatch):
    bot, session = bot_and_session

    users = UserRepo(db)
    chats = ChatRepo(db)
    settings = SettingsRepo(db)
    blacklist = BlacklistRepo(db)

    plugin = Plugin()

    # monkeypatch API request to return OK
    def fake_request(method: str, path: str, **kwargs):
        return SimpleNamespace(status_code=200)

    plugin._api._request = fake_request
    r = plugin.call_api_command("play")
    assert getattr(r, "status_code", None) == 200
