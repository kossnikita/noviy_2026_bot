"""Integration tests for slot wins WebSocket broadcast end-to-end."""

import asyncio
import hashlib

from fastapi.testclient import TestClient

from api.app import create_app
from api.db_sa import ApiToken, Base, create_db
from api.slot import _broadcast_slot_win_async


def _create_app_and_client():
    """Create app with auth token and test client."""
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
    return c, app


def test_websocket_receives_slot_win_broadcast():
    """Test that WebSocket client receives slot_win message when prize is created."""
    c, app = _create_app_and_client()

    # Create prize first
    r = c.post(
        "/slot/prize", json={"name": "test_prize", "title": "Test Prize"}
    )
    assert r.status_code == 201

    # Connect WebSocket client
    with c.websocket_connect("/ws/player") as ws:
        # Clear the initial state message
        initial_msg = ws.receive_json()
        assert initial_msg["type"] == "state"

        # Create a prize win
        r = c.post(
            "/slot/win",
            json={"wins": [{"user_id": 123, "prize_name": "test_prize"}]},
        )
        assert r.status_code == 201
        win_data = r.json()[0]

        # Manually broadcast (since TestClient doesn't execute BackgroundTasks)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                _broadcast_slot_win_async(app.state.player, win_data)
            )
        finally:
            loop.close()

        # Should receive the slot_win message
        msg = ws.receive_json()
        assert msg["type"] == "slot_win"
        assert msg["user_id"] == 123
        assert msg["prize"]["name"] == "test_prize"
        assert msg["prize"]["title"] == "Test Prize"


def test_multiple_websockets_receive_broadcast():
    """Test that multiple connected WebSocket clients all receive the broadcast."""
    c, app = _create_app_and_client()

    # Create prize
    r = c.post("/slot/prize", json={"name": "p1", "title": "Prize 1"})
    assert r.status_code == 201

    # Connect two WebSocket clients
    with c.websocket_connect("/ws/player") as ws1:
        with c.websocket_connect("/ws/player") as ws2:
            # Clear initial state messages
            ws1.receive_json()
            ws2.receive_json()

            # Create a prize win
            r = c.post(
                "/slot/win",
                json={"wins": [{"user_id": 456, "prize_name": "p1"}]},
            )
            assert r.status_code == 201
            win_data = r.json()[0]

            # Manually broadcast
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    _broadcast_slot_win_async(app.state.player, win_data)
                )
            finally:
                loop.close()

            # Both clients should receive the slot_win message
            msg1 = ws1.receive_json()
            msg2 = ws2.receive_json()

            assert msg1["type"] == "slot_win"
            assert msg2["type"] == "slot_win"
            assert msg1["user_id"] == 456
            assert msg2["user_id"] == 456


def test_slot_win_message_contains_all_fields():
    """Test that slot_win message contains all required fields."""
    c, app = _create_app_and_client()

    # Create prize
    r = c.post(
        "/slot/prize",
        json={"name": "grand_prize", "title": "Grand Prize 🎉"},
    )
    assert r.status_code == 201

    with c.websocket_connect("/ws/player") as ws:
        # Clear initial state
        ws.receive_json()

        # Create win with specific data
        r = c.post(
            "/slot/win",
            json={"wins": [{"user_id": 789, "prize_name": "grand_prize"}]},
        )
        assert r.status_code == 201
        win_data = r.json()[0]

        # Manually broadcast
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                _broadcast_slot_win_async(app.state.player, win_data)
            )
        finally:
            loop.close()

        # Receive slot_win message
        slot_win_msg = ws.receive_json()
        assert slot_win_msg["type"] == "slot_win"

        # Verify all required fields
        assert "id" in slot_win_msg
        assert "user_id" in slot_win_msg
        assert slot_win_msg["user_id"] == 789
        assert "prize" in slot_win_msg
        assert "name" in slot_win_msg["prize"]
        assert "title" in slot_win_msg["prize"]
        assert slot_win_msg["prize"]["title"] == "Grand Prize 🎉"
        assert "won_at" in slot_win_msg

        # Verify it matches the win response
        assert slot_win_msg["id"] == win_data["id"]
        assert slot_win_msg["user_id"] == win_data["user_id"]


def test_multiple_wins_broadcast_separately():
    """Test that multiple wins are broadcast as separate messages."""
    c, app = _create_app_and_client()

    # Create prize
    r = c.post("/slot/prize", json={"name": "p", "title": "Prize"})
    assert r.status_code == 201

    with c.websocket_connect("/ws/player") as ws:
        # Clear initial state
        ws.receive_json()

        # Create multiple wins at once
        r = c.post(
            "/slot/win",
            json={
                "wins": [
                    {"user_id": 111, "prize_name": "p"},
                    {"user_id": 222, "prize_name": "p"},
                    {"user_id": 333, "prize_name": "p"},
                ]
            },
        )
        assert r.status_code == 201
        wins = r.json()
        assert len(wins) == 3

        # Manually broadcast each win
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            for win_data in wins:
                loop.run_until_complete(
                    _broadcast_slot_win_async(app.state.player, win_data)
                )
        finally:
            loop.close()

        # Collect all slot_win messages
        slot_win_messages = []
        for _ in range(3):
            msg = ws.receive_json()
            if msg.get("type") == "slot_win":
                slot_win_messages.append(msg)

        # Should receive 3 slot_win messages
        assert len(slot_win_messages) == 3

        # Verify we got all three user_ids
        user_ids = {msg["user_id"] for msg in slot_win_messages}
        assert user_ids == {111, 222, 333}
