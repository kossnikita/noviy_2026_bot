"""Compatibility shim.

Tracks closure scheduler is implemented by the tracks system plugin.
"""

from bot.plugins.system.tracks.tracks_closure import run_tracks_closure_scheduler

__all__ = ["run_tracks_closure_scheduler"]
