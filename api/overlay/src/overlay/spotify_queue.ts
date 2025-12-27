// spotify_queue.ts: helper for queuing upcoming Spotify tracks

export type SpotifyQueueSummary = {
    playlistIds: string[];
    playlistIndex: number;
    spotifyTrackId: string | null;
    sequentialAdvance: boolean;
};

export type SpotifyState = "state";

const MAX_PRELOAD = 64;

export class SpotifyQueueManager {
    private queuedSpotifyIds = new Set<string>();
    private lastPlaylistIndex: number | null = null;

    constructor(private enqueue: (spotifyId: string) => Promise<void>) { }

    summarize(state: Record<string, any>, fallbackSpotifyId: string | null = null): SpotifyQueueSummary {
        const rawPlaylist = Array.isArray(state.playlist) ? state.playlist : [];
        const playlistIds = rawPlaylist
            .map((item) => (item && item.spotify_id ? String(item.spotify_id) : ""))
            .map((id) => id.trim())
            .filter(Boolean);
        let playlistIndex = typeof state.index === "number" ? state.index : -1;
        if (playlistIds.length) {
            if (playlistIndex < 0) playlistIndex = 0;
            if (playlistIndex >= playlistIds.length) playlistIndex = playlistIds.length - 1;
        } else {
            playlistIndex = -1;
        }
        const playlistSpotifyId =
            playlistIndex >= 0 && playlistIndex < playlistIds.length
                ? playlistIds[playlistIndex]
                : "";
        const spotifyTrackId = playlistSpotifyId || (fallbackSpotifyId?.trim() || "");
        const sequentialAdvance =
            playlistIndex >= 0 &&
            this.lastPlaylistIndex !== null &&
            playlistIndex === this.lastPlaylistIndex + 1;
        this.lastPlaylistIndex = playlistIndex >= 0 ? playlistIndex : null;
        return {
            playlistIds,
            playlistIndex,
            spotifyTrackId: spotifyTrackId || null,
            sequentialAdvance,
        };
    }

    async preload(summary: SpotifyQueueSummary) {
        const { playlistIds, playlistIndex } = summary;
        if (playlistIndex < 0 || !playlistIds.length) {
            this.queuedSpotifyIds.clear();
            return;
        }
        const futureIds = playlistIds.slice(playlistIndex + 1);
        if (!futureIds.length) {
            this.queuedSpotifyIds.clear();
            return;
        }
        const toQueue = futureIds.slice(0, MAX_PRELOAD);
        for (const id of toQueue) {
            if (this.queuedSpotifyIds.has(id)) continue;
            try {
                await this.enqueue(id);
                this.queuedSpotifyIds.add(id);
            } catch (err) {
                console.warn("spotify_queue: failed to enqueue", err);
                break;
            }
        }
        const futureSet = new Set(futureIds);
        for (const queued of Array.from(this.queuedSpotifyIds)) {
            if (!futureSet.has(queued)) {
                this.queuedSpotifyIds.delete(queued);
            }
        }
    }

    shouldUseNext(summary: SpotifyQueueSummary): boolean {
        const id = summary.spotifyTrackId;
        if (!id) return false;
        if (!summary.sequentialAdvance) return false;
        if (!this.queuedSpotifyIds.has(id)) return false;
        this.queuedSpotifyIds.delete(id);
        return true;
    }

    consume(trackId: string | null) {
        if (trackId) this.queuedSpotifyIds.delete(trackId);
    }

    reset() {
        this.queuedSpotifyIds.clear();
        this.lastPlaylistIndex = null;
    }
}
