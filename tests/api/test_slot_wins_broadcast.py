"""Tests for slot wins WebSocket broadcast functionality."""

import asyncio
import hashlib
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from starlette.websockets import WebSocket

from api.app import create_app
from api.db_sa import ApiToken, Base, create_db
from api.slot import _broadcast_slot_win_async


def _client():
    """Create a test client with auth token."""
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


def test_broadcast_slot_win_async_sends_to_all_clients():
    """Test that _broadcast_slot_win_async sends message to all connected clients."""
    c, app = _client()

    # Create mocks for WebSocket connections
    mock_ws1 = AsyncMock(spec=WebSocket)
    mock_ws2 = AsyncMock(spec=WebSocket)

    # Add mocks to player controller
    app.state.player.clients.add(mock_ws1)
    app.state.player.clients.add(mock_ws2)

    win_data = {
        "id": 1,
        "user_id": 123,
        "prize": {"name": "test_prize", "title": "Test Prize"},
        "won_at": "2025-12-31T12:00:00Z",
    }

    # Run the async function
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(
            _broadcast_slot_win_async(app.state.player, win_data)
        )
    finally:
        loop.close()

    # Verify both clients received the message
    mock_ws1.send_json.assert_called_once()
    mock_ws2.send_json.assert_called_once()

    # Verify message structure
    call_args = mock_ws1.send_json.call_args[0][0]
    assert call_args["type"] == "slot_win"
    assert call_args["id"] == 1
    assert call_args["user_id"] == 123
    assert call_args["prize"]["title"] == "Test Prize"
    assert call_args["won_at"] == "2025-12-31T12:00:00Z"


def test_broadcast_slot_win_async_removes_dead_clients():
    """Test that _broadcast_slot_win_async removes clients that fail to receive message."""
    c, app = _client()

    # Create mocks: one succeeds, one fails
    mock_ws_ok = AsyncMock(spec=WebSocket)
    mock_ws_dead = AsyncMock(spec=WebSocket)
    mock_ws_dead.send_json.side_effect = Exception("Connection closed")

    # Add mocks to player controller
    app.state.player.clients.add(mock_ws_ok)
    app.state.player.clients.add(mock_ws_dead)

    initial_count = len(app.state.player.clients)
    assert initial_count == 2

    win_data = {
        "id": 2,
        "user_id": 456,
        "prize": {"name": "big_prize", "title": "Big Prize"},
        "won_at": "2025-12-31T13:00:00Z",
    }

    # Run the async function
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(
            _broadcast_slot_win_async(app.state.player, win_data)
        )
    finally:
        loop.close()

    # Verify dead client was removed
    assert len(app.state.player.clients) == 1
    assert mock_ws_ok in app.state.player.clients
    assert mock_ws_dead not in app.state.player.clients


def test_create_wins_triggers_broadcast():
    """Test that creating wins triggers WebSocket broadcast in background."""
    c, app = _client()

    # Create prize first
    r = c.post("/slot/prize", json={"name": "p1", "title": "Prize 1"})
    assert r.status_code == 201

    # Mock the broadcast function to track calls
    with patch("api.slot._broadcast_slot_win_bg") as mock_broadcast:
        # Create win
        r = c.post(
            "/slot/win",
            json={
                "wins": [
                    {"user_id": 123, "prize_name": "p1"},
                    {"user_id": 456, "prize_name": "p1"},
                ]
            },
        )
        assert r.status_code == 201

        # Give background tasks a moment to be scheduled
        import time

        time.sleep(0.1)

        # Verify broadcast was scheduled for each win
        assert mock_broadcast.call_count == 2

        # Verify the data passed to broadcast
        calls = mock_broadcast.call_args_list
        assert calls[0][0][1]["user_id"] == 123
        assert calls[1][0][1]["user_id"] == 456


def test_create_wins_broadcast_message_structure():
    """Test that broadcast message has correct structure."""
    c, app = _client()

    # Create prize
    r = c.post(
        "/slot/prize", json={"name": "test_prize", "title": "Test Prize"}
    )
    assert r.status_code == 201

    # Mock WebSocket clients
    mock_ws = AsyncMock(spec=WebSocket)
    app.state.player.clients.add(mock_ws)

    # Create win
    r = c.post(
        "/slot/win",
        json={"wins": [{"user_id": 999, "prize_name": "test_prize"}]},
    )
    assert r.status_code == 201
    win_response = r.json()[0]

    # Verify broadcast message structure
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        # Manually call broadcast with the response data
        loop.run_until_complete(
            _broadcast_slot_win_async(
                app.state.player,
                win_response,
            )
        )
    finally:
        loop.close()

    # Verify message was sent with correct structure
    assert mock_ws.send_json.called
    msg = mock_ws.send_json.call_args[0][0]
    assert msg["type"] == "slot_win"
    assert msg["id"] == win_response["id"]
    assert msg["user_id"] == 999
    assert msg["prize"]["name"] == "test_prize"
    assert msg["prize"]["title"] == "Test Prize"
    assert "won_at" in msg


def test_broadcast_with_no_connected_clients():
    """Test that broadcast handles case with no connected clients gracefully."""
    c, app = _client()

    # Ensure no clients are connected
    assert len(app.state.player.clients) == 0

    win_data = {
        "id": 1,
        "user_id": 123,
        "prize": {"name": "p1", "title": "Prize 1"},
        "won_at": "2025-12-31T12:00:00Z",
    }

    # Should not raise any exception
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(
            _broadcast_slot_win_async(app.state.player, win_data)
        )
    finally:
        loop.close()

    # Still no clients
    assert len(app.state.player.clients) == 0


def test_broadcast_with_multiple_clients_partial_failure():
    """Test broadcast with multiple clients where some fail and some succeed."""
    c, app = _client()

    # Create mocks: 3 clients, middle one fails
    mock_ws1 = AsyncMock(spec=WebSocket)
    mock_ws2 = AsyncMock(spec=WebSocket)
    mock_ws2.send_json.side_effect = Exception("Network error")
    mock_ws3 = AsyncMock(spec=WebSocket)

    app.state.player.clients.add(mock_ws1)
    app.state.player.clients.add(mock_ws2)
    app.state.player.clients.add(mock_ws3)

    win_data = {
        "id": 1,
        "user_id": 123,
        "prize": {"name": "p1", "title": "Prize 1"},
        "won_at": "2025-12-31T12:00:00Z",
    }

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(
            _broadcast_slot_win_async(app.state.player, win_data)
        )
    finally:
        loop.close()

    # Verify all were attempted
    mock_ws1.send_json.assert_called_once()
    mock_ws2.send_json.assert_called_once()
    mock_ws3.send_json.assert_called_once()

    # Verify only the failed one was removed
    assert len(app.state.player.clients) == 2
    assert mock_ws1 in app.state.player.clients
    assert mock_ws2 not in app.state.player.clients
    assert mock_ws3 in app.state.player.clients
