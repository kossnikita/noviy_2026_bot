"""Scheduler for checking track durations.

Runs every hour and removes tracks longer than the maximum allowed duration.
Notifies users whose tracks were removed.
"""

import asyncio
import logging
from typing import TYPE_CHECKING

from aiogram import Bot

from bot.api_repos import SpotifyTracksRepo
from bot.integrations.spotify_client import SpotifyClient

if TYPE_CHECKING:
    pass

_LOG = logging.getLogger("tracks_duration_check")

# Maximum track duration: 5 minutes 12 seconds = 312 seconds = 312000 ms
MAX_TRACK_DURATION_MS = 5 * 60 * 1000 + 12 * 1000  # 312000 ms


def _format_duration(ms: int) -> str:
    """Format milliseconds as MM:SS."""
    total_seconds = ms // 1000
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes}:{seconds:02d}"


async def run_tracks_duration_check_scheduler(
    bot: Bot,
    tracks_repo: SpotifyTracksRepo,
    spotify: SpotifyClient,
    *,
    poll_seconds: float = 3600.0,  # 1 hour
) -> None:
    """Check track durations and remove tracks that exceed the limit.

    Runs every hour (by default).
    For each track that is too long:
    - Deletes it from the database
    - Sends a notification to the user who added it
    """

    _LOG.info(
        "Tracks duration check scheduler started (interval=%.0fs, max_duration=%sms)",
        poll_seconds,
        MAX_TRACK_DURATION_MS,
    )

    while True:
        try:
            await _check_track_durations(bot, tracks_repo, spotify)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            _LOG.warning("Tracks duration check error: %s", e)

        await asyncio.sleep(poll_seconds)


async def _check_track_durations(
    bot: Bot,
    tracks_repo: SpotifyTracksRepo,
    spotify: SpotifyClient,
) -> None:
    """Single pass: check all tracks and remove those that are too long."""

    if not spotify.is_configured():
        _LOG.debug("Spotify not configured, skipping duration check")
        return

    # Get all tracks from the database
    try:
        all_tracks = await asyncio.to_thread(tracks_repo.list_all)
    except Exception as e:
        _LOG.warning("Failed to list tracks: %s", e)
        return

    if not all_tracks:
        _LOG.debug("No tracks in database")
        return

    _LOG.debug("Checking %d tracks for duration limits", len(all_tracks))

    removed_count = 0
    for track_record in all_tracks:
        try:
            track_id = track_record.get("id")
            spotify_id = track_record.get("spotify_id")
            track_name = track_record.get("name") or "Unknown"
            track_artist = track_record.get("artist") or "Unknown"
            added_by = track_record.get("added_by")

            if not spotify_id or not track_id or not added_by:
                continue

            # Get track info from Spotify to check duration
            try:
                spotify_track = await asyncio.to_thread(
                    spotify.get_track, spotify_id
                )
            except Exception as e:
                _LOG.debug(
                    "Failed to get track info from Spotify for %s: %s",
                    spotify_id,
                    e,
                )
                continue

            duration_ms = spotify_track.duration_ms

            if duration_ms > MAX_TRACK_DURATION_MS:
                _LOG.info(
                    "Track exceeds duration limit: %s - %s (%s, limit %s), user_id=%s",
                    track_artist,
                    track_name,
                    _format_duration(duration_ms),
                    _format_duration(MAX_TRACK_DURATION_MS),
                    added_by,
                )

                # Delete the track
                try:
                    await asyncio.to_thread(tracks_repo.delete_by_id, track_id)
                    _LOG.info(
                        "Deleted track id=%s spotify_id=%s",
                        track_id,
                        spotify_id,
                    )
                except Exception as e:
                    _LOG.warning(
                        "Failed to delete track id=%s: %s", track_id, e
                    )
                    continue

                # Notify the user
                max_duration_str = _format_duration(MAX_TRACK_DURATION_MS)
                track_duration_str = _format_duration(duration_ms)

                message_text = (
                    f"⚠️ <b>Трек удалён из списка</b>\n\n"
                    f"Ваш трек <b>{track_artist}</b> — <b>{track_name}</b> "
                    f"был удалён, так как его длительность ({track_duration_str}) "
                    f"превышает максимально допустимую ({max_duration_str}).\n\n"
                    f"Пожалуйста, замените его на другой трек с помощью команды /track."
                )

                try:
                    await bot.send_message(added_by, message_text)
                    _LOG.info(
                        "Notified user %s about removed track %s",
                        added_by,
                        spotify_id,
                    )
                except Exception as e:
                    _LOG.warning(
                        "Failed to notify user %s about removed track: %s",
                        added_by,
                        e,
                    )

                removed_count += 1

        except Exception as e:
            _LOG.warning("Error processing track %s: %s", track_record, e)
            continue

    if removed_count > 0:
        _LOG.info("Removed %d tracks exceeding duration limit", removed_count)
