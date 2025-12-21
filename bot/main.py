import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from aiogram.types.bot_command_scope_all_private_chats import BotCommandScopeAllPrivateChats
from aiogram.types.bot_command_scope_chat import BotCommandScopeChat

from bot.config import load_config
from bot.db import (
    init_db,
    UserRepo,
    ChatRepo,
    BlacklistRepo,
    SettingsRepo,
    SpotifyTracksRepo,
)
from bot.integrations.spotify_client import SpotifyClient
from bot.plugins.loader import registry
from bot.routers.common import setup_common_router
from bot.routers.admin import setup_admin_router
from bot.routers.group_events import setup_group_router
from bot.middlewares.activity import ActivityMiddleware
from bot.routers.tracks import setup_tracks_router
from bot.middlewares.command_logging import CommandLoggingMiddleware
from bot.middlewares.registration_required import RegistrationRequiredMiddleware
from bot.routers.unknown_commands import setup_unknown_commands_router
from bot.schedulers.tracks_closure import run_tracks_closure_scheduler


def _env_flag(name: str, default: bool = False) -> bool:
    val = (os.getenv(name) or "").strip().lower()
    if not val:
        return default
    return val in {"1", "true", "yes", "y", "on"}


async def _run_api_server(*, db, host: str, port: int) -> None:
    import uvicorn

    from bot.api.app import create_app

    app = create_app(db=db)
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        access_log=False,
        log_config=None,
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main() -> None:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    logger = logging.getLogger("bot")

    cfg = load_config()
    logger.info("Config loaded. DB path=%s", cfg.db_path)

    db = init_db(database_url=cfg.database_url, db_path=cfg.db_path)
    logger.info("Database initialized (SQLAlchemy + Alembic)")
    users = UserRepo(db)
    chats = ChatRepo(db)

    bot = Bot(cfg.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    # Log command invocations (/start, /track, etc.)
    dp.message.middleware(CommandLoggingMiddleware())
    # Block any private actions until user ran /start and is in DB
    dp.message.middleware(RegistrationRequiredMiddleware(users))
    # Touch user activity for any message/callback via middleware (non-blocking)
    dp.message.middleware(ActivityMiddleware(users))
    dp.callback_query.middleware(ActivityMiddleware(users))
    dp.callback_query.middleware(RegistrationRequiredMiddleware(users))

    # Load plugins and register their handlers
    registry.load_contest_plugins()
    try:
        from bot.plugins.loader import registry as _r
        logger.info("Loaded %d plugin(s)", len(_r.plugins))
    except Exception:
        logger.info("Plugins loaded")

    # Routers
    blacklist = BlacklistRepo(db)
    settings = SettingsRepo(db)
    tracks_repo = SpotifyTracksRepo(db)
    spotify = SpotifyClient(cfg.spotify_client_id, cfg.spotify_client_secret)

    common_router = setup_common_router(users, cfg.admin_id, settings, blacklist)
    admin_router = setup_admin_router(users, chats, cfg.admin_id, blacklist, settings)
    group_router = setup_group_router(chats, users)
    tracks_router = setup_tracks_router(
        tracks_repo,
        spotify,
        cfg.max_tracks_per_user,
        settings,
    )
    unknown_router = setup_unknown_commands_router()

    # Let plugins register their handlers into the same routers
    registry.register_all(common_router, admin_router)

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
    dp.include_router(tracks_router)
    dp.include_router(unknown_router)
    logger.info(
        "Routers included (order): %s",
        " -> ".join(
            [
                common_router.name,
                admin_router.name,
                group_router.name,
                tracks_router.name,
                unknown_router.name,
            ]
        ),
    )
    logger.info("Starting polling...")

    api_task: asyncio.Task[None] | None = None
    if _env_flag("API_ENABLED", default=False):
        api_host = (os.getenv("API_HOST") or "0.0.0.0").strip()
        api_port = int((os.getenv("API_PORT") or "8000").strip())
        logger.info("Starting FastAPI server on %s:%s", api_host, api_port)
        api_task = asyncio.create_task(
            _run_api_server(db=db, host=api_host, port=api_port)
        )

    scheduler_task = asyncio.create_task(
        run_tracks_closure_scheduler(bot, settings, chats)
    )
    try:
        await dp.start_polling(bot)
    finally:
        if api_task is not None:
            api_task.cancel()
        scheduler_task.cancel()
        try:
            if api_task is not None:
                await api_task
            await scheduler_task
        except Exception:
            pass
        logger.info("Polling stopped.")


if __name__ == "__main__":
    asyncio.run(main())
