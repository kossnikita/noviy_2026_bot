import pytest
import pytest_asyncio

from aiogram import Bot

from .fakes import FakeSession


@pytest.fixture()
def admin_id() -> int:
    return 999


@pytest_asyncio.fixture()
async def bot_and_session():
    session = FakeSession()
    bot = Bot(token="42:TEST", session=session)
    try:
        yield bot, session
    finally:
        await bot.session.close()
