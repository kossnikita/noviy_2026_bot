from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.types import BufferedInputFile

from bot.api_repos import ApiError, _Api
from bot.routers.vouchers import _make_qr_png_bytes


async def run_voucher_sync(
    *,
    bot: Bot,
    api: _Api,
    interval_s: float = 10.0,
) -> None:
    log = logging.getLogger("bot.vouchers.sync")
    log.info("Voucher sync started (interval_s=%.2f)", interval_s)

    while True:
        try:
            # 1) Cleanup: delete Telegram messages for vouchers that have been used.
            # Fetch all active voucher messages (deleted_at IS NULL)
            try:
                messages_to_check = await asyncio.to_thread(
                    api.get_json,
                    "/slot/voucher-messages?active_only=1&limit=1000&offset=0",
                )
            except ApiError as e:
                log.warning("Failed to fetch voucher messages: %s", e)
                messages_to_check = []

            for msg_record in messages_to_check or []:
                try:
                    db_record_id = int((msg_record or {}).get("id") or 0)
                    user_id = int((msg_record or {}).get("user_id") or 0)
                    message_id = int((msg_record or {}).get("message_id") or 0)
                    voucher_code = str(
                        (msg_record or {}).get("voucher_code") or ""
                    ).strip()

                    if (
                        not db_record_id
                        or not user_id
                        or not voucher_code
                        or not message_id
                    ):
                        log.debug(f"Invalid message record: {msg_record}")
                        continue

                    # Lookup current voucher state from API
                    try:
                        voucher_list = await asyncio.to_thread(
                            api.get_json,
                            f"/slot/voucher?code={voucher_code}&user_id={user_id}",
                        )
                    except ApiError as lookup_err:
                        log.debug(
                            f"API error looking up voucher {voucher_code}: {lookup_err}"
                        )
                        continue

                    if not voucher_list:
                        # Voucher no longer exists - mark message as deleted in DB
                        log.info(
                            f"Voucher {voucher_code} not found, marking "
                            f"message {message_id} as deleted for user {user_id}"
                        )
                        try:
                            api.delete(
                                f"/slot/voucher-messages/{db_record_id}"
                            )
                        except ApiError as e:
                            log.warning(
                                f"Failed to mark message {msg_id} as deleted: {e}"
                            )
                        continue

                    v = (
                        voucher_list[0]
                        if isinstance(voucher_list, list)
                        else None
                    )
                    if v is None:
                        log.info(
                            f"Voucher {voucher_code} disappeared, marking "
                            f"message {message_id} as deleted"
                        )
                        try:
                            await asyncio.to_thread(
                                api.delete,
                                f"/slot/voucher-messages/{db_record_id}",
                            )
                        except ApiError as e:
                            log.warning(
                                f"Failed to mark message {db_record_id} as deleted: {e}"
                            )
                        continue

                    use_count = int((v or {}).get("use_count") or 0)
                    total_games = int((v or {}).get("total_games") or 1)

                    log.debug(
                        f"Voucher {voucher_code}: use_count={use_count}, "
                        f"total_games={total_games}, remaining={total_games - use_count}"
                    )

                    # Voucher is exhausted when use_count >= total_games
                    if use_count >= total_games:
                        log.info(
                            f"Voucher {voucher_code} exhausted "
                            f"(use_count={use_count} >= total_games={total_games}), "
                            f"deleting Telegram message {message_id} for user {user_id}"
                        )
                        try:
                            await bot.delete_message(
                                chat_id=user_id,
                                message_id=message_id,
                                revoke=True,
                            )
                            log.info(
                                f"Successfully deleted Telegram message "
                                f"{message_id} for user {user_id}"
                            )
                        except Exception as e:
                            log.warning(
                                f"Failed to delete Telegram message "
                                f"{message_id} for user {user_id}: {e}"
                            )

                        # Mark in API DB as deleted
                        try:
                            await asyncio.to_thread(
                                api.delete,
                                f"/slot/voucher-messages/{db_record_id}",
                            )
                        except ApiError as e:
                            log.warning(
                                f"Failed to mark DB record {db_record_id} as deleted: {e}"
                            )

                except Exception as e:
                    log.warning(
                        f"Error processing message record {msg_record}: {e}"
                    )

            # 2) Delivery: send new voucher DMs (vouchers with no message record yet)
            try:
                vouchers = await asyncio.to_thread(
                    api.get_json,
                    "/slot/voucher?active_only=1&limit=1000&offset=0",
                )
            except ApiError as e:
                log.warning("Failed to fetch vouchers: %s", e)
                vouchers = []

            for v in vouchers or []:
                try:
                    user_id_val = (v or {}).get("user_id")
                    if user_id_val is None:
                        log.debug(f"Invalid user_id in voucher: {v}")
                        continue
                    user_id = int(user_id_val)

                    code = str((v or {}).get("code") or "").strip()
                    if not code:
                        log.warning(f"Voucher missing code: {v}")
                        continue

                    # Check if we already have a message record for this user+code
                    try:
                        query = f"/slot/voucher-messages?user_id={user_id}&"
                        query += f"voucher_code={code}&active_only=1"
                        existing = await asyncio.to_thread(api.get_json, query)
                    except ApiError as e:
                        log.debug(f"API error checking message records: {e}")
                        existing = []

                    if existing:
                        log.debug(
                            f"Message already sent for voucher {code} to user {user_id}, skipping"
                        )
                        continue

                    # New voucher - send DM to user
                    log.info(f"Sending new voucher {code} to user {user_id}")
                    png = _make_qr_png_bytes(code)
                    photo = BufferedInputFile(
                        png, filename=f"voucher_{code}.png"
                    )
                    try:
                        sent = await bot.send_photo(
                            chat_id=user_id,
                            photo=photo,
                            caption=f"Ваш ваучер: <b>{code}</b>",
                        )
                        log.info(
                            f"Sent voucher {code} to user {user_id} (message_id={sent.message_id})"
                        )

                        # Record the message in API DB
                        try:
                            await asyncio.to_thread(
                                api.post_json,
                                "/slot/voucher-messages",
                                {
                                    "user_id": int(user_id),
                                    "voucher_code": code,
                                    "message_id": int(sent.message_id),
                                },
                            )
                            log.info(
                                f"Recorded message {sent.message_id} for voucher {code} in DB"
                            )
                        except ApiError as e:
                            log.warning(
                                f"Failed to record message in API DB: {e}"
                            )

                    except Exception as e:
                        log.warning(
                            f"Failed to send voucher DM: user_id={user_id} code={code} err={e}"
                        )

                except Exception as e:
                    log.warning(f"Error processing voucher {v}: {e}")

        except Exception:
            log.exception("Voucher sync loop crashed")

        await asyncio.sleep(interval_s)
