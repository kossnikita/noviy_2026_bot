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


def test_photos_create_and_list_offset():
    c = _client()

    r1 = c.post(
        "/photos", json={"name": "a.jpg", "url": "/img/a.jpg", "added_by": 1}
    )
    assert r1.status_code == 201
    id1 = int(r1.json()["id"])

    r2 = c.post(
        "/photos", json={"name": "b.jpg", "url": "/img/b.jpg", "added_by": 2}
    )
    assert r2.status_code == 201
    id2 = int(r2.json()["id"])
    assert id2 > id1

    lst = c.get("/photos?limit=10&offset=0")
    assert lst.status_code == 200
    items = lst.json()
    assert len(items) == 2
    # default ordering is newest-first
    assert int(items[0]["id"]) == id2
    assert int(items[1]["id"]) == id1

    lst2 = c.get("/photos?limit=1&offset=1")
    assert lst2.status_code == 200
    items2 = lst2.json()
    assert len(items2) == 1
    assert int(items2[0]["id"]) == id1


def test_photos_list_after_id_cursor():
    c = _client()

    ids: list[int] = []
    for n in range(5):
        r = c.post(
            "/photos",
            json={"name": f"{n}.jpg", "url": f"/img/{n}.jpg", "added_by": 1},
        )
        assert r.status_code == 201
        ids.append(int(r.json()["id"]))

    after = ids[1]
    r2 = c.get(f"/photos?limit=10&after_id={after}")
    assert r2.status_code == 200
    items = r2.json()
    got_ids = [int(x["id"]) for x in items]
    assert got_ids == [i for i in ids if i > after]
