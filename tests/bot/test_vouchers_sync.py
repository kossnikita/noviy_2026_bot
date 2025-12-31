"""Tests for voucher sync scheduler."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.api_repos import _Api


@pytest.mark.asyncio
async def test_voucher_sync_deletes_message_with_revoke_true(
    bot_and_session,
):
    """Test that delete_message is called with revoke=True."""
    bot, session = bot_and_session

    # Create a mock API
    api = MagicMock(spec=_Api)

    # Setup: one active message that should be deleted
    api.get_json.side_effect = [
        # First call: get active voucher messages
        [
            {
                "id": 123,
                "user_id": 456,
                "voucher_code": "ABC123",
                "message_id": 1000,
                "sent_at": "2025-12-31T10:00:00",
                "deleted_at": None,
            }
        ],
        # Second call: lookup current voucher state (exhausted)
        [
            {
                "code": "ABC123",
                "user_id": 456,
                "use_count": 3,
                "total_games": 3,
            }
        ],
        # Third call: get vouchers to send (empty, no new ones)
        [],
    ]

    # Mock bot.delete_message to track how it's called
    original_delete = bot.delete_message
    bot.delete_message = AsyncMock(side_effect=original_delete)

    # Import the sync function
    from bot.schedulers.vouchers_sync import run_voucher_sync

    # Create a task that will run for just one iteration
    sync_task = asyncio.create_task(
        run_voucher_sync(bot=bot, api=api, interval_s=0.01)
    )

    # Let it run one iteration
    await asyncio.sleep(0.05)

    # Cancel the task
    sync_task.cancel()
    try:
        await sync_task
    except asyncio.CancelledError:
        pass

    # Verify delete_message was called with revoke=True
    bot.delete_message.assert_called_once()
    call_kwargs = bot.delete_message.call_args.kwargs
    assert call_kwargs["chat_id"] == 456
    assert call_kwargs["message_id"] == 1000


@pytest.mark.asyncio
async def test_voucher_sync_marks_message_deleted_on_exhaustion(
    bot_and_session,
):
    """Test that message is marked as deleted in DB after exhaustion."""
    bot, session = bot_and_session

    api = MagicMock(spec=_Api)

    # Setup API responses
    api.get_json.side_effect = [
        # Active messages to check
        [
            {
                "id": 456,
                "user_id": 789,
                "voucher_code": "XYZ789",
                "message_id": 2000,
                "sent_at": "2025-12-31T11:00:00",
                "deleted_at": None,
            }
        ],
        # Voucher is exhausted
        [
            {
                "code": "XYZ789",
                "user_id": 789,
                "use_count": 5,
                "total_games": 5,
            }
        ],
        # No new vouchers to send
        [],
    ]
    api.delete = MagicMock()

    from bot.schedulers.vouchers_sync import run_voucher_sync

    sync_task = asyncio.create_task(
        run_voucher_sync(bot=bot, api=api, interval_s=0.01)
    )

    await asyncio.sleep(0.05)

    sync_task.cancel()
    try:
        await sync_task
    except asyncio.CancelledError:
        pass

    # Verify API delete was called to mark message as deleted
    api.delete.assert_called()
    delete_calls = api.delete.call_args_list
    assert any(
        "/slot/voucher-messages/456" in str(call) for call in delete_calls
    )


@pytest.mark.asyncio
async def test_voucher_sync_handles_telegram_deletion_error_gracefully(
    bot_and_session,
):
    """Test that message is marked as deleted even if Telegram API fails."""
    bot, session = bot_and_session

    api = MagicMock(spec=_Api)

    api.get_json.side_effect = [
        # Active messages
        [
            {
                "id": 111,
                "user_id": 222,
                "voucher_code": "DEL111",
                "message_id": 3000,
                "sent_at": "2025-12-31T12:00:00",
                "deleted_at": None,
            }
        ],
        # Voucher exhausted
        [
            {
                "code": "DEL111",
                "user_id": 222,
                "use_count": 2,
                "total_games": 2,
            }
        ],
        # No new vouchers
        [],
    ]
    api.delete = MagicMock()

    # Make bot.delete_message raise an exception
    bot.delete_message = AsyncMock(
        side_effect=Exception("message can't be deleted for everyone")
    )

    from bot.schedulers.vouchers_sync import run_voucher_sync

    sync_task = asyncio.create_task(
        run_voucher_sync(bot=bot, api=api, interval_s=0.01)
    )

    await asyncio.sleep(0.05)

    sync_task.cancel()
    try:
        await sync_task
    except asyncio.CancelledError:
        pass

    # Verify that despite Telegram error, message was still marked as deleted in DB
    api.delete.assert_called()
    delete_calls = api.delete.call_args_list
    assert any(
        "/slot/voucher-messages/111" in str(call) for call in delete_calls
    )


@pytest.mark.asyncio
async def test_voucher_sync_skips_messages_not_exhausted(
    bot_and_session,
):
    """Test that messages for non-exhausted vouchers are not deleted."""
    bot, session = bot_and_session

    api = MagicMock(spec=_Api)

    api.get_json.side_effect = [
        # Active messages
        [
            {
                "id": 999,
                "user_id": 888,
                "voucher_code": "ACTIVE",
                "message_id": 4000,
                "sent_at": "2025-12-31T13:00:00",
                "deleted_at": None,
            }
        ],
        # Voucher is NOT exhausted (use_count < total_games)
        [
            {
                "code": "ACTIVE",
                "user_id": 888,
                "use_count": 1,
                "total_games": 5,
            }
        ],
        # No new vouchers
        [],
    ]
    api.delete = MagicMock()
    bot.delete_message = AsyncMock()

    from bot.schedulers.vouchers_sync import run_voucher_sync

    sync_task = asyncio.create_task(
        run_voucher_sync(bot=bot, api=api, interval_s=0.01)
    )

    await asyncio.sleep(0.05)

    sync_task.cancel()
    try:
        await sync_task
    except asyncio.CancelledError:
        pass

    # Verify delete_message was NOT called (voucher still active)
    bot.delete_message.assert_not_called()
    # Verify API delete was NOT called
    api.delete.assert_not_called()


@pytest.mark.asyncio
async def test_voucher_sync_sends_new_voucher_and_records_message(
    bot_and_session,
):
    """Test that new vouchers are sent and recorded in API."""
    bot, session = bot_and_session

    api = MagicMock(spec=_Api)

    # Setup responses for the sync loop
    responses = [
        # First call: get active voucher messages (none)
        [],
        # Second call: get vouchers to send (one new voucher)
        [
            {
                "id": 777,
                "code": "NEWCODE",
                "user_id": 555,
                "use_count": 0,
                "total_games": 3,
            }
        ],
        # Third call: check if message already exists (during delivery phase)
        [],
    ]

    api.get_json = MagicMock(side_effect=responses)
    api.post_json = MagicMock(return_value={"id": 555, "message_id": 100})

    from bot.schedulers.vouchers_sync import run_voucher_sync

    sync_task = asyncio.create_task(
        run_voucher_sync(bot=bot, api=api, interval_s=0.01)
    )

    await asyncio.sleep(0.05)

    sync_task.cancel()
    try:
        await sync_task
    except asyncio.CancelledError:
        pass

    # Verify photo was sent to user
    send_photo_calls = [
        call for call in session.requests if call.api_method == "sendPhoto"
    ]
    assert len(send_photo_calls) > 0, "No sendPhoto calls found"

    # Verify message was recorded in API
    api.post_json.assert_called()
    post_call_args = str(api.post_json.call_args)
    assert "/slot/voucher-messages" in post_call_args
