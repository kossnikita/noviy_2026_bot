from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient

from api.app import create_app
from api.db_sa import ApiToken, Base, SpotifyTrack, create_db


def _client_with_tracks() -> TestClient:
    db = create_db(database_url="sqlite+pysqlite:///:memory:", db_path=":memory:")
    Base.metadata.create_all(db.engine)

    token = "TEST_TOKEN"
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with db.session() as s:
        s.add(ApiToken(token_hash=token_hash, label="test"))
        s.commit()

    with db.session() as s:
        s.add_all(
            [
                SpotifyTrack(
                    spotify_id="sp1",
                    name="Song1",
                    artist="Artist",
                    url=None,
                    added_by=1,
                ),
                SpotifyTrack(
                    spotify_id="sp2",
                    name="Song2",
                    artist="Artist",
                    url=None,
                    added_by=1,
                ),
            ]
        )
        s.commit()

    app = create_app(db=db)
    c = TestClient(app)
    # Keep token on client for HTTP too, if needed in future tests.
    c.headers.update({"Authorization": f"Bearer {token}"})
    return c


def test_ws_player_state_and_controls():
    c = _client_with_tracks()

    with c.websocket_connect("/ws/player?token=TEST_TOKEN") as ws:
        initial = ws.receive_json()
        assert initial["type"] == "state"
        assert initial["playlist"]
        assert initial["index"] == 0
        assert initial["current"]["spotify_id"] == "sp1"
        assert initial["playing"] is False

        ws.send_json({"op": "play"})
        state = ws.receive_json()
        assert state["type"] == "state"
        assert state["playing"] is True

        ws.send_json({"op": "next"})
        state = ws.receive_json()
        assert state["type"] == "state"
        assert state["index"] == 1
        assert state["current"]["spotify_id"] == "sp2"

        ws.send_json({"op": "pause"})
        state = ws.receive_json()
        assert state["type"] == "state"
        assert state["playing"] is False

        ws.send_json({"op": "get_playlist"})
        pl = ws.receive_json()
        assert pl["type"] == "playlist"
        assert len(pl["playlist"]) == 2


def test_ws_player_set_index_validation():
    c = _client_with_tracks()

    with c.websocket_connect("/ws/player?token=TEST_TOKEN") as ws:
        _ = ws.receive_json()

        ws.send_json({"op": "set_index", "index": 999})
        err = ws.receive_json()
        assert err["type"] == "error"
