import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Bot

from bot.db import ChatRepo, SettingsRepo


_LOG = logging.getLogger("tracks_closure")

_CLOSE_TS_KEY = "tracks_close_at_ts"
_ANNOUNCED_FOR_TS_KEY = "tracks_close_announced_for_ts"


def _get_close_ts(settings: SettingsRepo) -> int | None:
    raw = (settings.get(_CLOSE_TS_KEY, "") or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


async def run_tracks_closure_scheduler(
    bot: Bot,
    settings: SettingsRepo,
    chats: ChatRepo,
    *,
    poll_seconds: float = 30.0,
) -> None:
    """Announce 15 minutes before track list closes.

    Stores last announced close timestamp in settings to avoid repeats.
    """

    while True:
        try:
            close_ts = _get_close_ts(settings)
            if close_ts is not None:
                now_ts = int(datetime.now(timezone.utc).timestamp())
                announce_from = close_ts - 15 * 60

                announced_for = (settings.get(_ANNOUNCED_FOR_TS_KEY, "0") or "0").strip()
                try:
                    announced_for_ts = int(announced_for)
                except ValueError:
                    announced_for_ts = 0

                if announce_from <= now_ts < close_ts and announced_for_ts != close_ts:
                    close_dt = datetime.fromtimestamp(close_ts, tz=timezone.utc)
                    text = (
                        "⚠️ Внимание! Список треков закроется через 15 минут.\n"
                        "После закрытия нельзя добавлять или удалять треки.\n\n"
                        f"Время закрытия (UTC): {close_dt:%Y-%m-%d %H:%M}"
                    )

                    sent = 0
                    for chat_id in chats.group_chat_ids():
                        try:
                            await bot.send_message(chat_id, text)
                            sent += 1
                        except Exception:
                            pass

                    settings.set(_ANNOUNCED_FOR_TS_KEY, str(close_ts))
                    _LOG.info(
                        "Sent tracks close announcement to %s group chats for close_ts=%s",
                        sent,
                        close_ts,
                    )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            _LOG.warning("Tracks closure scheduler error: %s", e)

        await asyncio.sleep(poll_seconds)
