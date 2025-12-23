"""Common entrypoint to run bot + API together.

Usage:
  python -m main

"""

from __future__ import annotations

import asyncio


def main() -> None:
    from bot.main import main as bot_main

    asyncio.run(bot_main())


if __name__ == "__main__":
    main()
