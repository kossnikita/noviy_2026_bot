import asyncio
import logging
import os
import threading
from dataclasses import dataclass

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from aiogram.types.bot_command_scope_all_private_chats import BotCommandScopeAllPrivateChats
from aiogram.types.bot_command_scope_chat import BotCommandScopeChat

from bot.config import load_config
from bot.api_repos import (
    ApiSettings,
    BlacklistRepo,
    ChatRepo,
    SettingsRepo,
    UserRepo,
    _Api,
    _api_base_url_from_env,
)
from bot.plugins.loader import registry
from bot.routers.common import setup_common_router
from bot.routers.admin import setup_admin_router
from bot.routers.group_events import setup_group_router
from bot.middlewares.activity import ActivityMiddleware
from bot.middlewares.command_logging import CommandLoggingMiddleware
from bot.middlewares.clear_tracks_wait_on_command import (
    ClearTracksWaitOnCommandMiddleware,
)
from bot.middlewares.registration_required import RegistrationRequiredMiddleware
from bot.routers.unknown_commands import setup_unknown_commands_router


async def _run_api_server(*, host: str, port: int) -> None:
    raise RuntimeError("Deprecated: API server now runs in a background thread")


@dataclass
class _ApiServerHandle:
    server: object
    thread: threading.Thread


def _start_api_server_thread(*, host: str, port: int) -> _ApiServerHandle:
    import uvicorn

    from api.app import create_app

    app = create_app()
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        access_log=False,
        log_config=None,
    )
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, name="api-uvicorn", daemon=True)
    thread.start()
    return _ApiServerHandle(server=server, thread=thread)


async def _wait_api_ready(*, base_url: str, timeout_s: float = 10.0) -> None:
    import time

    start = time.time()
    api = _Api(ApiSettings(base_url=base_url, timeout_s=1.0))
    while True:
        try:
            r = api._request("GET", "/health")
            if r.status_code == 200:
                return
        except Exception:
            pass
        if (time.time() - start) >= timeout_s:
            return
        await asyncio.sleep(0.2)


async def main() -> None:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    logger = logging.getLogger("bot")

    cfg = load_config()
    logger.info("Config loaded. DB path=%s", cfg.db_path)

    api_host = "0.0.0.0"
    api_port = 8080
    api_base_url = _api_base_url_from_env(fallback_port=api_port)

    logger.info("Starting FastAPI server on %s:%s", api_host, api_port)
    api_server = _start_api_server_thread(host=api_host, port=api_port)
    await _wait_api_ready(base_url=api_base_url)

    api = _Api(ApiSettings(base_url=api_base_url, timeout_s=5.0))
    users = UserRepo(api)
    chats = ChatRepo(api)

    bot = Bot(cfg.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    # Log command invocations (/start, /track, etc.)
    dp.message.middleware(CommandLoggingMiddleware())
    # If user is in tracks "waiting" state and sends a command, drop that state
    dp.message.middleware(ClearTracksWaitOnCommandMiddleware())
    # Block any private actions until user ran /start and is in DB
    dp.message.middleware(RegistrationRequiredMiddleware(users))
    # Touch user activity for any message/callback via middleware (non-blocking)
    dp.message.middleware(ActivityMiddleware(users))
    dp.callback_query.middleware(ActivityMiddleware(users))
    dp.callback_query.middleware(RegistrationRequiredMiddleware(users))

    # Load plugins and register their handlers
    registry.load_all_plugins()
    try:
        from bot.plugins.loader import registry as _r
        logger.info(
            "Loaded %d contest plugin(s), %d system plugin(s)",
            len(_r.plugins),
            len(_r.system_plugins),
        )
    except Exception:
        logger.info("Plugins loaded")

    # Routers
    blacklist = BlacklistRepo(api)
    settings = SettingsRepo(api)

    common_router = setup_common_router(users, cfg.admin_id, settings, blacklist)
    admin_router = setup_admin_router(users, chats, cfg.admin_id, blacklist, settings)
    group_router = setup_group_router(chats, users)
    unknown_router = setup_unknown_commands_router()

    # Let plugins register their handlers. System plugins may also hook group router.
    registry.register_all(common_router, admin_router, group_router)

    # Configure visible command menus (MenuButton / Commands)
    try:
        user_commands = [
            BotCommand(command="start", description="Запуск и меню"),
            BotCommand(command="menu", description="Показать конкурсы"),
            BotCommand(command="track", description="Добавить трек в список"),
            BotCommand(command="mytracks", description="Мои добавленные треки"),
        ]
        await bot.set_my_commands(user_commands, scope=BotCommandScopeAllPrivateChats())
        logger.info(
            "Registered menu commands for private chats: %s",
            ", ".join([f"/{c.command}" for c in user_commands]),
        )

        admin_commands = [
            BotCommand(command="admin", description="Админ-панель"),
            BotCommand(command="announce", description="Объявление в группы"),
            BotCommand(command="tracks_close", description="Закрыть изменения треков"),
            BotCommand(command="tracks_limit", description="Лимит треков на пользователя"),
            BotCommand(command="blacklist_add", description="ЧС: добавить тег"),
            BotCommand(command="blacklist_remove", description="ЧС: удалить тег"),
            BotCommand(command="blacklist_list", description="ЧС: список"),
            BotCommand(command="toggle_new_users", description="Вкл/выкл приём новых"),
        ]
        # Set admin commands for admin's private chat specifically
        await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=cfg.admin_id))
        logger.info(
            "Registered menu commands for admin chat: %s",
            ", ".join([f"/{c.command}" for c in admin_commands]),
        )
        logger.info(
            "Bot commands set: default=%d admin=%d",
            len(user_commands),
            len(admin_commands),
        )
    except Exception as e:
        logger.warning("Failed to set bot commands: %s", e)

    dp.include_router(common_router)
    dp.include_router(admin_router)
    dp.include_router(group_router)
    dp.include_router(unknown_router)
    logger.info(
        "Routers included (order): %s",
        " -> ".join(
            [
                common_router.name,
                admin_router.name,
                group_router.name,
                unknown_router.name,
            ]
        ),
    )
    logger.info("Starting polling...")

    plugin_tasks = registry.start_system_background_tasks(bot)
    try:
        await dp.start_polling(bot)
    finally:
        if api_server is not None:
            try:
                setattr(api_server.server, "should_exit", True)
            except Exception:
                pass

        for t in plugin_tasks:
            t.cancel()
        for t in plugin_tasks:
            try:
                await t
            except Exception:
                pass

        if api_server is not None:
            api_server.thread.join(timeout=5)
        logger.info("Polling stopped.")


if __name__ == "__main__":
    asyncio.run(main())
