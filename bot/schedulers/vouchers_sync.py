from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.types import BufferedInputFile

from bot.api_repos import ApiError, SettingsRepo, _Api
from bot.routers.vouchers import (
    _VOUCHER_STATE_KEY_PREFIX,
    _decode_state,
    _encode_state,
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

    while True:
        try:
            # 1) Cleanup: delete messages for vouchers that have been used.
            offset = 0
            limit = 200
            state_keys: list[str] = []

            while True:
                try:
                    page = api.get_json(
                        f"/settings?limit={limit}&offset={offset}"
                    )
                except ApiError as e:
                    log.warning("Settings list failed: %s", e)
                    break

                items = page or []
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
                raw = settings.get(key)
                st = _decode_state(raw)
                if not st:
                    continue

                code = str(st.get("code") or "").strip()
                msg_id = int(st.get("message_id") or 0)
                issued_use_count = int(st.get("use_count") or 0)

                if not code or msg_id <= 0:
                    continue

                try:
                    user_id = int(key[len(_VOUCHER_STATE_KEY_PREFIX) :])
                except Exception:
                    continue

                try:
                    v = api.get_json(f"/vouchers/by-code/{code}")
                except ApiError:
                    # If voucher disappeared, just drop the state.
                    try:
                        api.delete(f"/settings/{key}")
                    except Exception:
                        pass
                    continue

                use_count = int((v or {}).get("use_count") or 0)
                if use_count > issued_use_count:
                    try:
                        await bot.delete_message(
                            chat_id=user_id, message_id=msg_id
                        )
                    except Exception:
                        pass
                    try:
                        api.delete(f"/settings/{key}")
                    except Exception:
                        pass

            # 2) Delivery: send voucher DM only when a new voucher is present in API.
            v_offset = 0
            v_limit = 200
            while True:
                try:
                    vouchers = api.get_json(
                        f"/vouchers?active_only=1&limit={v_limit}&offset={v_offset}"
                    )
                except ApiError as e:
                    log.warning("Voucher list failed: %s", e)
                    break

                items = vouchers or []
                if not items:
                    break

                for v in items:
                    try:
                        user_id = int((v or {}).get("user_id"))
                    except Exception:
                        continue

                    code = str((v or {}).get("code") or "").strip()
                    if not code:
                        continue

                    use_count = int((v or {}).get("use_count") or 0)

                    state_key = f"{_VOUCHER_STATE_KEY_PREFIX}{user_id}"
                    prev = _decode_state(settings.get(state_key))
                    prev_code = (
                        str((prev or {}).get("code") or "").strip()
                        if prev
                        else ""
                    )

                    # "New voucher appeared" = no state for user, or code has changed.
                    if prev_code == code:
                        continue

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
                    except Exception as e:
                        # User might not have started the bot / blocked DMs.
                        log.info(
                            "Failed to DM voucher: user_id=%s err=%s",
                            user_id,
                            e,
                        )
                        continue

                    try:
                        settings.set(
                            state_key,
                            _encode_state(
                                code=code,
                                message_id=int(sent.message_id),
                                use_count=use_count,
                            ),
                        )
                    except Exception as e:
                        log.warning(
                            "Failed to persist voucher state: user_id=%s err=%s",
                            user_id,
                            e,
                        )

                if len(items) < v_limit:
                    break
                v_offset += v_limit

        except Exception:
            log.exception("Voucher sync loop crashed")

        await asyncio.sleep(interval_s)
