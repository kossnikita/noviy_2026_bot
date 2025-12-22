# Party Contests Telegram Bot

Modular Telegram bot for party contests with admin panel and drop-in contest plugins.

Database/models are hosted by the FastAPI service (package `api/`). The bot talks to it over HTTP.

## Features

- Admin panel with stats and broadcast
- SQLite for users and known chats
- Modular contest plugins (user + admin UI)
- Works in private chats and group chats
- Env-configured: token, admin ID, DB path

## Quick Start

1) Create and activate a virtual environment:

    ```bash
    python -m venv .venv
    . .venv/Scripts/activate
    ```

2) Install dependencies:

    ```bash
    pip install -r requirements.txt
    ```

3) Create .env from template and fill values:

    ```bash
    copy .env.example .env
    ```

    Set:

    - `BOT_TOKEN` – Telegram bot token
    - `ADMIN_ID` – numeric Telegram user ID of the admin
    - `DB_PATH` – path to SQLite DB (default: database.sqlite3)
    - `API_TOKEN` – shared API access token (used by bot and external apps)

    API requests must include a token:
    - `Authorization: Bearer <API_TOKEN>` (recommended)
    - or `X-API-Token: <API_TOKEN>`

4) Run bot + API together:

    ```bash
    python -m main
    ```

5) Add the bot to your group chat if desired. The bot records known group chats when added.

## Admin Commands

- `/admin` – Open admin panel
- `/announce <text>` – Broadcast message to all known group chats

## Extending with Contests

Drop a new plugin under `bot/plugins/contests/<your_plugin>/plugin.py` that exports a `Plugin` implementing the `ContestPlugin` protocol.

- Register user and admin handlers using your unique `slug` as callback/data prefix
- Provide `user_menu_button()` and optional `admin_menu_button()` to appear in menus

See: `bot/plugins/contests/sample_quiz/` for a minimal example.

## Notes

- This project uses `aiogram` v3 API.
- API server runs with FastAPI + SQLAlchemy + Alembic migrations.
