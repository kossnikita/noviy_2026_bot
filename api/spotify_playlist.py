"""
spotify_playlist.py: Spotify Playlist API integration.

Manages a single "Noviy Bot" playlist for synchronized playback.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

PLAYLIST_NAME = "Noviy Bot Queue"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"


class SpotifyPlaylistError(Exception):
    """Error during Spotify playlist operations."""

    pass


async def _spotify_request(
    method: str,
    path: str,
    token: str,
    json_body: dict | list | None = None,
    params: dict | None = None,
) -> dict | list | None:
    """Make an authenticated request to Spotify API."""
    url = f"{SPOTIFY_API_BASE}{path}"
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.request(
            method,
            url,
            headers=headers,
            json=json_body,
            params=params,
        )

        if resp.status_code == 204:
            return None

        if resp.status_code >= 400:
            logger.error(
                "Spotify API error: %s %s -> %s: %s",
                method,
                path,
                resp.status_code,
                resp.text,
            )
            raise SpotifyPlaylistError(
                f"Spotify API {method} {path} failed: {resp.status_code}"
            )

        return resp.json()


async def get_current_user_id(token: str) -> str:
    """Get the current user's Spotify ID."""
    data = await _spotify_request("GET", "/me", token)
    if not isinstance(data, dict) or "id" not in data:
        raise SpotifyPlaylistError("Failed to get user ID")
    return str(data["id"])


async def find_playlist_by_name(token: str, name: str) -> str | None:
    """Find a playlist by name in user's library. Returns playlist_id or None."""
    offset = 0
    limit = 50

    while True:
        data = await _spotify_request(
            "GET",
            "/me/playlists",
            token,
            params={"limit": limit, "offset": offset},
        )

        if not isinstance(data, dict):
            break

        items = data.get("items", [])
        if not items:
            break

        for playlist in items:
            if playlist.get("name") == name:
                return str(playlist["id"])

        if not data.get("next"):
            break

        offset += limit

    return None


async def create_playlist(token: str, user_id: str, name: str) -> str:
    """Create a new private playlist. Returns playlist_id."""
    data = await _spotify_request(
        "POST",
        f"/users/{user_id}/playlists",
        token,
        json_body={
            "name": name,
            "public": False,
            "description": "Auto-generated playlist for Noviy Bot streaming",
        },
    )

    if not isinstance(data, dict) or "id" not in data:
        raise SpotifyPlaylistError("Failed to create playlist")

    playlist_id = str(data["id"])
    logger.info("Created Spotify playlist: %s (id=%s)", name, playlist_id)
    return playlist_id


async def get_or_create_playlist(token: str, name: str = PLAYLIST_NAME) -> str:
    """Find existing playlist or create a new one. Returns playlist_id."""
    # First try to find existing playlist
    playlist_id = await find_playlist_by_name(token, name)
    if playlist_id:
        logger.info(
            "Found existing Spotify playlist: %s (id=%s)", name, playlist_id
        )
        return playlist_id

    # Create new playlist
    user_id = await get_current_user_id(token)
    return await create_playlist(token, user_id, name)


async def replace_playlist_tracks(
    token: str,
    playlist_id: str,
    spotify_ids: list[str],
) -> None:
    """Replace all tracks in a playlist with the given track IDs."""
    # Spotify API accepts max 100 tracks per request
    # For replace, we first clear then add in batches

    if not spotify_ids:
        # Clear playlist
        await _spotify_request(
            "PUT",
            f"/playlists/{playlist_id}/tracks",
            token,
            json_body={"uris": []},
        )
        logger.info("Cleared playlist %s", playlist_id)
        return

    # Convert to URIs
    uris = [f"spotify:track:{sid}" for sid in spotify_ids]

    # First batch: use PUT to replace (clears + adds first 100)
    first_batch = uris[:100]
    await _spotify_request(
        "PUT",
        f"/playlists/{playlist_id}/tracks",
        token,
        json_body={"uris": first_batch},
    )

    # Subsequent batches: use POST to append
    for i in range(100, len(uris), 100):
        batch = uris[i : i + 100]
        await _spotify_request(
            "POST",
            f"/playlists/{playlist_id}/tracks",
            token,
            json_body={"uris": batch},
        )

    logger.info(
        "Replaced playlist %s tracks: %d tracks total",
        playlist_id,
        len(spotify_ids),
    )


async def add_track_to_playlist(
    token: str,
    playlist_id: str,
    spotify_id: str,
) -> None:
    """Add a single track to the end of the playlist."""
    uri = f"spotify:track:{spotify_id}"
    await _spotify_request(
        "POST",
        f"/playlists/{playlist_id}/tracks",
        token,
        json_body={"uris": [uri]},
    )
    logger.info("Added track %s to playlist %s", spotify_id, playlist_id)


async def transfer_playback(
    token: str,
    device_id: str,
    play: bool = False,
) -> None:
    """Transfer playback to a specific device."""
    await _spotify_request(
        "PUT",
        "/me/player",
        token,
        json_body={"device_ids": [device_id], "play": play},
    )
    logger.info(
        "Transferred playback to device: %s (play=%s)", device_id, play
    )


async def start_playlist_playback(
    token: str,
    playlist_id: str,
    device_id: str | None = None,
    offset_index: int = 0,
) -> None:
    """Start playback of the playlist on a device."""
    # First transfer playback to the device to make it active
    if device_id:
        try:
            await transfer_playback(token, device_id, play=False)
        except SpotifyPlaylistError as e:
            logger.warning("Transfer playback failed (continuing): %s", e)

    context_uri = f"spotify:playlist:{playlist_id}"

    body: dict[str, Any] = {
        "context_uri": context_uri,
    }

    if offset_index > 0:
        body["offset"] = {"position": offset_index}

    params = {}
    if device_id:
        params["device_id"] = device_id

    await _spotify_request(
        "PUT",
        "/me/player/play",
        token,
        json_body=body,
        params=params if params else None,
    )

    logger.info(
        "Started playlist playback: %s (device=%s, offset=%d)",
        playlist_id,
        device_id,
        offset_index,
    )


async def get_playback_state(token: str) -> dict | None:
    """Get current playback state."""
    try:
        data = await _spotify_request("GET", "/me/player", token)
        return data if isinstance(data, dict) else None
    except SpotifyPlaylistError:
        return None


async def pause_playback(token: str, device_id: str | None = None) -> None:
    """Pause playback."""
    params = {"device_id": device_id} if device_id else None
    await _spotify_request("PUT", "/me/player/pause", token, params=params)


async def resume_playback(token: str, device_id: str | None = None) -> None:
    """Resume playback."""
    params = {"device_id": device_id} if device_id else None
    await _spotify_request("PUT", "/me/player/play", token, params=params)


async def next_track(token: str, device_id: str | None = None) -> None:
    """Skip to next track."""
    params = {"device_id": device_id} if device_id else None
    await _spotify_request("POST", "/me/player/next", token, params=params)


async def previous_track(token: str, device_id: str | None = None) -> None:
    """Skip to previous track."""
    params = {"device_id": device_id} if device_id else None
    await _spotify_request("POST", "/me/player/previous", token, params=params)
