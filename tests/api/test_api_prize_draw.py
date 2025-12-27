import hashlib

from fastapi.testclient import TestClient

from api.app import create_app
from api.db_sa import ApiToken, Base, create_db


def _client_with_token() -> TestClient:
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
    c._test_db = db  # type: ignore[attr-defined]
    return c


def test_client_submits_wins_and_api_lists_them():
    c = _client_with_token()

    r0 = c.post("/slot/prize", json={"name": "p1", "title": "Prize 1"})
    assert r0.status_code == 201
    r1 = c.post("/slot/prize", json={"name": "p2", "title": "Prize 2"})
    assert r1.status_code == 201

    r = c.post(
        "/slot/win",
        json={
            "wins": [
                {"user_id": 123, "prize_name": "p1"},
                {"user_id": 123, "prize_name": "p2"},
            ]
        },
    )
    assert r.status_code == 201
    created = r.json()
    assert len(created) == 2
    assert created[0]["user_id"] == 123
    assert "prize" in created[0]
    assert created[0]["prize"]["name"] in {"p1", "p2"}
    assert created[0]["prize"]["title"] in {"Prize 1", "Prize 2"}

    r2 = c.get("/slot/win")
    assert r2.status_code == 200
    assert len(r2.json()) == 2

    r3 = c.get("/slot/win/by-user/123")
    assert r3.status_code == 200
    assert len(r3.json()) == 2

    r4 = c.get("/slot/win/count")
    assert r4.status_code == 200
    assert int(r4.json()["count"]) == 2
