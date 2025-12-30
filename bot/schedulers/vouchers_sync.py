from __future__ import annotations

import asyncio
import logging


import json
from aiogram import Bot
from aiogram.types import BufferedInputFile

from bot.api_repos import ApiError, SettingsRepo, _Api
from bot.routers.vouchers import (
    _VOUCHER_STATE_KEY_PREFIX,
    _decode_state,
    _make_qr_png_bytes,
)


async def run_voucher_sync(
    *,
    bot: Bot,
    api: _Api,
    settings: SettingsRepo,
    interval_s: float = 10.0,
) -> None:
    log = logging.getLogger("bot.vouchers.sync")
    log.info("Voucher sync started (interval_s=%.2f)", interval_s)

    while True:
        try:
            # 1) Cleanup: delete messages for vouchers that have been used.
            offset = 0
            limit = 200
            state_keys: list[str] = []

            while True:
                try:
                    log.debug(
                        f"Fetching settings page offset={offset} limit={limit}"
                    )
                    page = api.get_json(
                        f"/settings?limit={limit}&offset={offset}"
                    )
                except ApiError as e:
                    log.warning("Settings list failed: %s", e)
                    break

                items = page or []
                log.debug(
                    f"Fetched {len(items)} settings items at offset={offset}"
                )
                if not items:
                    break

                for it in items:
                    key = str((it or {}).get("key") or "")
                    if key.startswith(_VOUCHER_STATE_KEY_PREFIX):
                        state_keys.append(key)

                if len(items) < limit:
                    break
                offset += limit

            for key in state_keys:
                log.info(f"Processing state key: {key}")
                raw = settings.get(key)
                st = _decode_state(raw)
                log.debug(f"Decoded state for {key}: {st}")
                if not st:
                    log.debug(f"No state for {key}, skipping")
                    continue

                try:
                    user_id = int(key[len(_VOUCHER_STATE_KEY_PREFIX) :])
                except Exception:
                    log.warning(f"Invalid user_id in key: {key}")
                    continue

                codes = list(st.get("codes") or [])
                if not codes:
                    log.info(f"No codes for {key}, deleting key")
                    try:
                        api.delete(f"/settings/{key}")
                    except Exception as e:
                        log.warning(
                            f"Failed to delete empty state key {key}: {e}"
                        )
                    continue

                remaining = []
                for entry in codes:
                    code = str(entry.get("code") or "").strip()
                    msg_id = int(entry.get("message_id") or 0)

                    if not code or msg_id <= 0:
                        log.debug(f"Invalid code or msg_id in entry: {entry}")
                        continue

                    # Lookup voucher by code AND user_id using the list endpoint.
                    # We filter by user_id to avoid confusion if the voucher was reissued
                    # to a different user after being exhausted.
                    # On transient API errors we keep the entry to avoid spam on outages.
                    try:
                        voucher_list = api.get_json(
                            f"/slot/voucher?code={code}&user_id={user_id}"
                        )
                        log.debug(
                            f"Voucher lookup for code {code} user {user_id}: {voucher_list}"
                        )
                    except ApiError as lookup_err:
                        # API error (timeout/401/500) — do NOT drop entry, keep it.
                        log.warning(
                            f"API error looking up voucher {code}, keeping entry: {lookup_err}"
                        )
                        remaining.append(entry)
                        continue

                    # If the list is empty, voucher no longer exists — drop entry.
                    if not voucher_list:
                        log.info(
                            f"Voucher {code} not found (empty list), "
                            f"dropping entry for user {user_id}"
                        )
                        continue

                    # Take the first matching voucher from the list.
                    v = (
                        voucher_list[0]
                        if isinstance(voucher_list, list)
                        else None
                    )
                    if v is None:
                        log.info(
                            f"Voucher {code} disappeared, dropping entry for user {user_id}"
                        )
                        continue

                    use_count = int((v or {}).get("use_count") or 0)
                    total_games = int((v or {}).get("total_games") or 1)

                    log.debug(
                        f"Voucher {code}: use_count={use_count}, "
                        f"total_games={total_games}, remaining={total_games - use_count}"
                    )

                    # Voucher is exhausted when use_count >= total_games
                    if use_count >= total_games:
                        log.info(
                            f"Voucher {code} exhausted "
                            f"(use_count={use_count} >= total_games={total_games}), "
                            f"deleting message {msg_id} for user {user_id}"
                        )
                        try:
                            await bot.delete_message(
                                chat_id=user_id, message_id=msg_id
                            )
                            log.info(
                                f"Successfully deleted message {msg_id} for user {user_id}"
                            )
                        except Exception as e:
                            log.warning(
                                f"Failed to delete message {msg_id} for user {user_id}: {e}"
                            )
                        continue

                    # keep tracking this entry
                    remaining.append(entry)

                # Persist remaining entries or delete key if empty
                try:
                    if remaining:
                        log.info(
                            f"Persisting {len(remaining)} codes for {key}"
                        )
                        settings.set(
                            key,
                            json.dumps(
                                {"codes": remaining},
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                        )
                    else:
                        log.info(f"No remaining codes for {key}, deleting key")
                        api.delete(f"/settings/{key}")
                except Exception as e:
                    log.warning(
                        f"Failed to persist/delete state for {key}: {e}"
                    )

            # 2) Delivery: send voucher DM only when a new voucher is present in API.
            v_offset = 0
            v_limit = 200
            while True:
                try:
                    log.debug(
                        f"Fetching vouchers page offset={v_offset} limit={v_limit}"
                    )
                    vouchers = api.get_json(
                        f"/slot/voucher?active_only=1&limit={v_limit}&offset={v_offset}"
                    )
                except ApiError as e:
                    log.warning("Voucher list failed: %s", e)
                    break

                items = vouchers or []
                log.debug(
                    f"Fetched {len(items)} vouchers at offset={v_offset}"
                )
                if not items:
                    break

                for v in items:
                    try:
                        user_id_val = (v or {}).get("user_id")
                        if user_id_val is None:
                            log.warning(f"Invalid user_id in voucher: {v}")
                            continue
                        user_id = int(user_id_val)
                    except Exception:
                        log.warning(f"Invalid user_id in voucher: {v}")
                        continue

                    code = str((v or {}).get("code") or "").strip()
                    if not code:
                        log.warning(f"Voucher missing code: {v}")
                        continue

                    state_key = f"{_VOUCHER_STATE_KEY_PREFIX}{user_id}"
                    prev = _decode_state(settings.get(state_key))
                    log.debug(f"Decoded prev state for {state_key}: {prev}")
                    prev_codes = set()
                    if prev and isinstance(prev.get("codes"), list):
                        codes_list = prev.get("codes")
                        if codes_list:
                            for entry in codes_list:
                                try:
                                    prev_codes.add(
                                        str(
                                            (entry or {}).get("code") or ""
                                        ).strip()
                                    )
                                except Exception:
                                    continue

                    # "New voucher appeared" = code not previously sent to this user.
                    if code in prev_codes:
                        log.info(
                            f"Voucher {code} already sent to user {user_id}, skipping"
                        )
                        continue

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
                    except Exception as e:
                        log.info(
                            f"Failed to DM voucher: user_id={user_id} code={code} err={e}"
                        )
                        continue

                    try:
                        # Merge new entry into existing state.codes
                        # Note: we don't store use_count, we fetch it from API when needed
                        new_entry = {
                            "code": code,
                            "message_id": int(sent.message_id),
                        }
                        merged = {"codes": []}
                        if prev and isinstance(prev.get("codes"), list):
                            prev_codes_list = prev.get("codes")
                            if prev_codes_list:
                                merged["codes"].extend(prev_codes_list)
                        merged["codes"].append(new_entry)
                        settings.set(
                            state_key,
                            json.dumps(
                                merged,
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                        )
                        log.info(
                            f"Persisted new voucher {code} for user {user_id} in state"
                        )
                    except Exception as e:
                        log.warning(
                            f"Failed to persist voucher state: "
                            f"user_id={user_id} code={code} err={e}"
                        )

                if len(items) < v_limit:
                    log.debug(
                        f"No more vouchers to fetch (got {len(items)} < {v_limit}), breaking loop"
                    )
                    break
                v_offset += v_limit
                log.debug(f"Advancing voucher offset to {v_offset}")

        except Exception:
            log.exception("Voucher sync loop crashed")

        await asyncio.sleep(interval_s)
