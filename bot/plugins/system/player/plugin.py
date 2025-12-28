from __future__ import annotations

import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.enums import ChatType
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.api_repos import ApiSettings, _Api
from bot.config import load_config

_LOG = logging.getLogger("player")
_PLAYER_ADMIN_CB = "player:admin"
_PLAYER_CMD_CB_PREFIX = "player:cmd:"


class Plugin:
    name = "Player"

    def __init__(self) -> None:
        cfg = load_config()
        self._admin_id = int(cfg.admin_id)
        self._api = _Api(
            ApiSettings(
                base_url=cfg.api_base_url, timeout_s=15.0, token=cfg.api_token
            )
        )

    def user_menu_button(self):
        return None

    def keyboard(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="▶️ Воспроизвести",
                        callback_data=_PLAYER_CMD_CB_PREFIX + "play",
                    ),
                    InlineKeyboardButton(
                        text="⏸ Пауза",
                        callback_data=_PLAYER_CMD_CB_PREFIX + "pause",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="⏮ Предыдующий",
                        callback_data=_PLAYER_CMD_CB_PREFIX + "prev",
                    ),
                    InlineKeyboardButton(
                        text="⏭ Следующий",
                        callback_data=_PLAYER_CMD_CB_PREFIX + "next",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="🔀 Перемешать",
                        callback_data=_PLAYER_CMD_CB_PREFIX + "shuffle",
                    ),
                ],
            ]
        )

    def call_api_command(self, cmd: str):
        path = f"/player/{cmd}"
        return self._api._request("POST", path)

    def admin_menu_button(self):
        return ("🟢 Плеер оверлея", _PLAYER_ADMIN_CB)

    def register_user(self, router: Router) -> None:
        return

    def register_admin(self, router: Router) -> None:
        @router.message(Command("player"), F.chat.type == ChatType.PRIVATE)
        async def cmd_player(message: Message) -> None:
            if not message.from_user or message.from_user.id != self._admin_id:
                return
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="▶️ Воспроизвести",
                            callback_data=_PLAYER_CMD_CB_PREFIX + "play",
                        ),
                        InlineKeyboardButton(
                            text="⏸ Пауза",
                            callback_data=_PLAYER_CMD_CB_PREFIX + "pause",
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            text="⏮ Предыдующий",
                            callback_data=_PLAYER_CMD_CB_PREFIX + "prev",
                        ),
                        InlineKeyboardButton(
                            text="⏭ Следующий",
                            callback_data=_PLAYER_CMD_CB_PREFIX + "next",
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            text="🔀 Перемешать",
                            callback_data=_PLAYER_CMD_CB_PREFIX + "shuffle",
                        ),
                    ],
                ]
            )
            await message.answer("Пульт управления оверлеем:", reply_markup=kb)

        @router.callback_query(F.data == _PLAYER_ADMIN_CB)
        async def admin_panel(cb: CallbackQuery) -> None:
            if not cb.from_user or cb.from_user.id != self._admin_id:
                return
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="▶️ Воспроизвести",
                            callback_data=_PLAYER_CMD_CB_PREFIX + "play",
                        ),
                        InlineKeyboardButton(
                            text="⏸ Пауза",
                            callback_data=_PLAYER_CMD_CB_PREFIX + "pause",
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            text="⏮ Предыдующий",
                            callback_data=_PLAYER_CMD_CB_PREFIX + "prev",
                        ),
                        InlineKeyboardButton(
                            text="⏭ Следующий",
                            callback_data=_PLAYER_CMD_CB_PREFIX + "next",
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            text="🔀 Перемешать",
                            callback_data=_PLAYER_CMD_CB_PREFIX + "shuffle",
                        ),
                    ],
                ]
            )
            await cb.answer()
            if cb.message:
                await cb.message.answer(
                    "Пульт управления оверлеем:", reply_markup=kb
                )

        @router.callback_query(F.data.startswith(_PLAYER_CMD_CB_PREFIX))
        async def handle_cmd(cb: CallbackQuery) -> None:
            if not cb.from_user or cb.from_user.id != self._admin_id:
                return
            cmd = (cb.data or "").split(":", 2)[-1]
            path = f"/player/{cmd}"
            try:
                r = self._api._request("POST", path)
            except Exception as e:
                _LOG.exception("API request failed: %s", e)
                await cb.answer("Ошибка API", show_alert=True)
                return
            if r.status_code >= 400:
                await cb.answer(f"API error: {r.status_code}", show_alert=True)
                return
            await cb.answer(f"Выполнено: {cmd}")
            # Removed stray end patch marker
