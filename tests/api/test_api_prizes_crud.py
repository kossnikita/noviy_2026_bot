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

    r = c.post(
        "/prizes",
        json={"name": "p1", "friendly_name": "Prize 1", "weight": 2.5},
    )
    assert r.status_code == 201
    pid = int(r.json()["id"])

    r = c.get(f"/prizes/{pid}")
    assert r.status_code == 200
    assert r.json()["name"] == "p1"

    r = c.get("/prizes")
    assert r.status_code == 200
    assert len(r.json()) == 1

    r = c.put(f"/prizes/{pid}", json={"friendly_name": "Prize 1b"})
    assert r.status_code == 200
    assert r.json()["friendly_name"] == "Prize 1b"

    r = c.put(f"/prizes/remaining/{pid}", json={"remaining": 3})
    assert r.status_code == 200
    assert r.json()["prize_id"] == pid
    assert r.json()["remaining"] == 3

    r = c.get(f"/prizes/remaining/{pid}")
    assert r.status_code == 200
    assert r.json()["remaining"] == 3

    r = c.get("/prizes/remaining")
    assert r.status_code == 200
    assert any(int(x["prize_id"]) == pid for x in r.json())

    r = c.put(f"/prizes/remaining/{pid}", json={"remaining": 0})
    assert r.status_code == 200
    assert r.json()["remaining"] == 0

    r = c.delete(f"/prizes/remaining/{pid}")
    assert r.status_code == 200

    r = c.delete(f"/prizes/{pid}")
    assert r.status_code == 204


def test_prize_wins_endpoints():
    c = _client()

    r = c.post(
        "/prizes",
        json={"name": "p1", "friendly_name": "Prize 1", "weight": 1.0},
    )
    pid = int(r.json()["id"])
    c.put(f"/prizes/remaining/{pid}", json={"remaining": 1})

    vr = c.post("/vouchers", json={"user_id": 777})
    assert vr.status_code == 201
    code = vr.json()["code"]

    r = c.post("/prizes/draw", json={"voucher": code})
    assert r.status_code == 200

    r = c.get("/prizes/wins")
    assert r.status_code == 200
    assert len(r.json()) == 1

    r = c.get("/prizes/wins/by-user/777")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert int(r.json()[0]["user_id"]) == 777

    r = c.get("/prizes/wins/count")
    assert r.status_code == 200
    assert int(r.json()["count"]) == 1
