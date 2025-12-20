import pytest
import pytest_asyncio

from aiogram import Bot

from bot.db_sa import Base, create_db

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


@pytest.fixture()
def db():
    # In-memory DB for fast, isolated tests.
    db = create_db(database_url="sqlite+pysqlite:///:memory:", db_path=":memory:")
    Base.metadata.create_all(db.engine)
    return db
