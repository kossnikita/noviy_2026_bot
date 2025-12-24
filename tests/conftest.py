import pytest
from api.db_sa import Base, create_db


@pytest.fixture()
def db():
    # In-memory DB for fast, isolated tests.
    db = create_db(
        database_url="sqlite+pysqlite:///:memory:", db_path=":memory:"
    )
    Base.metadata.create_all(db.engine)
    return db
