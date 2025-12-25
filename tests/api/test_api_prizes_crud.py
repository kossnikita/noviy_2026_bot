import hashlib

from fastapi.testclient import TestClient

from api.app import create_app
from api.db_sa import ApiToken, Base, create_db


def _client() -> TestClient:
    db = create_db(
        database_url="sqlite+pysqlite:///:memory:", db_path=":memory:"
    )
    Base.metadata.create_all(db.engine)

    token = "TEST_TOKEN"
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with db.session() as s:
        s.add(ApiToken(token_hash=token_hash, label="test"))
        s.commit()

    app = create_app(db=db)
    c = TestClient(app)
    c.headers.update({"Authorization": f"Bearer {token}"})
    return c


def test_prizes_crud_and_remaining_upsert():
    c = _client()

    r = c.post("/slot", json={"name": "p1", "title": "Prize 1"})
    assert r.status_code == 201

    r = c.post(
        "/slot/wins",
        json={
            "wins": [{"user_id": 1, "prize_name": "p1"}]
        },
    )
    assert r.status_code == 201


def test_prize_wins_endpoints():
    c = _client()

    r = c.post("/slot", json={"name": "p1", "title": "Prize 1"})
    assert r.status_code == 201

    r = c.post(
        "/slot/wins",
        json={
            "wins": [{"user_id": 777, "prize_name": "p1"}]
        },
    )
    assert r.status_code == 201

    r = c.get("/slot/wins")
    assert r.status_code == 200
    assert len(r.json()) == 1

    r = c.get("/slot/wins/by-user/777")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert int(r.json()[0]["user_id"]) == 777

    r = c.get("/slot/wins/count")
    assert r.status_code == 200
    assert int(r.json()["count"]) == 1
