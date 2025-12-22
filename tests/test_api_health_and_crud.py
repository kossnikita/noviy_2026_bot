import hashlib

from fastapi.testclient import TestClient

from api.app import create_app
from api.db_sa import ApiToken, Base, create_db


def _client():
    db = create_db(database_url="sqlite+pysqlite:///:memory:", db_path=":memory:")
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


def _client_no_auth():
    db = create_db(database_url="sqlite+pysqlite:///:memory:", db_path=":memory:")
    Base.metadata.create_all(db.engine)
    app = create_app(db=db)
    return TestClient(app)


def test_health():
    c = _client()
    r = c.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_requires_token_returns_401_not_500():
    c = _client_no_auth()
    r = c.get("/users")
    assert r.status_code == 401
    assert "detail" in (r.json() or {})


def test_users_crud():
    c = _client()

    r = c.post(
        "/users",
        json={
            "id": 1,
            "username": "alice",
            "first_name": "Alice",
            "last_name": None,
            "is_admin": False,
            "is_blacklisted": False,
        },
    )
    assert r.status_code == 201
    assert r.json()["id"] == 1

    r = c.get("/users/1")
    assert r.status_code == 200
    assert r.json()["username"] == "alice"

    r = c.put("/users/1", json={"is_admin": True})
    assert r.status_code == 200
    assert r.json()["is_admin"] is True

    r = c.get("/users")
    assert r.status_code == 200
    assert len(r.json()) == 1

    r = c.delete("/users/1")
    assert r.status_code == 204


def test_settings_upsert_and_delete():
    c = _client()

    r = c.put("/settings/allow_new_users", json={"value": "1"})
    assert r.status_code == 200
    assert r.json()["key"] == "allow_new_users"
    assert r.json()["value"] == "1"

    r = c.get("/settings/allow_new_users")
    assert r.status_code == 200

    r = c.delete("/settings/allow_new_users")
    assert r.status_code == 204


def test_blacklist_crud_normalizes_tag():
    c = _client()

    r = c.post("/blacklist", json={"tag": "@BadGuy", "note": "no"})
    assert r.status_code == 201
    assert r.json()["tag"] == "badguy"

    r = c.get("/blacklist/badguy")
    assert r.status_code == 200

    r = c.put("/blacklist/@badguy", json={"note": "updated"})
    assert r.status_code == 200
    assert r.json()["note"] == "updated"

    r = c.delete("/blacklist/badguy")
    assert r.status_code == 204


def test_spotify_tracks_crud_and_unique_spotify_id():
    c = _client()

    r = c.post(
        "/spotify-tracks",
        json={
            "spotify_id": "sp1",
            "name": "Song",
            "artist": "Artist",
            "url": "https://example.com",
            "added_by": 10,
        },
    )
    assert r.status_code == 201
    tid = r.json()["id"]

    r = c.post(
        "/spotify-tracks",
        json={
            "spotify_id": "sp1",
            "name": "Song",
            "artist": "Artist",
            "url": None,
            "added_by": 11,
        },
    )
    assert r.status_code == 409

    r = c.put(f"/spotify-tracks/{tid}", json={"name": "Song2"})
    assert r.status_code == 200
    assert r.json()["name"] == "Song2"

    r = c.get(f"/spotify-tracks/{tid}")
    assert r.status_code == 200

    r = c.delete(f"/spotify-tracks/{tid}")
    assert r.status_code == 204
