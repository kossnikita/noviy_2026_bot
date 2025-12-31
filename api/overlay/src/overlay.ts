import { cleanBaseUrl, resolveUrl } from "./utils";
import { OverlayConfig } from "./overlay/types";
import { coverImg, photoImg, statusEl, trackLayer } from "./overlay/dom";
import { applyAnimation } from "./overlay/dom_helpers";
import { getUserName } from "./overlay/overlay_helpers";
import { wsConnect } from "./overlay/ws";
import { renderTrack } from "./overlay/track_render";
import { pollPhotosLoop } from "./overlay/overlay_loops";
import { showPhoto } from "./overlay/photo_helpers";
import {
    hideSpotifyEmbed,
    showSpotifyAuthPanel,
    setupSpotifyAuthButton,
} from "./overlay/spotify_auth";
import {
    fetchSpotifyAccessTokenFromBackend as fetchSpotifyAccessTokenFromBackendModule,
    getSpotifyAccessToken as getSpotifyAccessTokenModule,
} from "./overlay/spotify_sdk";
import { initSlotWins, handleSlotWinMessage } from "./overlay/slot_wins";

declare global {
    interface Window {
        __NOVIY_OVERLAY__?: Partial<OverlayConfig>;
    }
}

let lastPhotoId = 0;
let lastStateVersion = 0;
let currentSpotifyTrackId: string | null = null;

// Cache of spotify_id -> added_by user ID from backend playlist
let trackUserCache: Map<string, number> = new Map();

function setStatus(text: string) {
    if (!statusEl) return;
    statusEl.textContent = text;
}

const cfg: OverlayConfig = {
    OVERLAY_API_TOKEN: (window.__NOVIY_OVERLAY__?.OVERLAY_API_TOKEN || "").trim(),
    WS_URL: (window.__NOVIY_OVERLAY__?.WS_URL || "").trim(),
    PHOTO_POLL_INTERVAL_MS: Number(window.__NOVIY_OVERLAY__?.PHOTO_POLL_INTERVAL_MS ?? 2000),
    PHOTO_DISPLAY_MS: Number(window.__NOVIY_OVERLAY__?.PHOTO_DISPLAY_MS ?? 10000),
    QUEUE_POLL_INTERVAL_MS: Number(window.__NOVIY_OVERLAY__?.QUEUE_POLL_INTERVAL_MS ?? 2000),
    SPOTIFY_OAUTH_TOKEN: (function loadSpotifyToken(): string | undefined {
        let t = (window.__NOVIY_OVERLAY__?.SPOTIFY_OAUTH_TOKEN || "") as string;
        if (!t) t = (window as any).__NOVIY_ENV__?.SPOTIFY_OAUTH_TOKEN || (window as any).SPOTIFY_OAUTH_TOKEN || "";
        if (!t) {
            try {
                const meta = document.querySelector('meta[name="SPOTIFY_OAUTH_TOKEN"]') as HTMLMetaElement | null;
                if (meta && meta.content) t = meta.content;
            } catch {
                /* ignore DOM errors */
            }
        }
        if (typeof t === "string") t = t.trim();
        if (!t) {
            console.warn(
                "overlay: SPOTIFY_OAUTH_TOKEN not provided in page config; " +
                "will try to fetch it from backend (/api/spotify/token) when needed."
            );
            return undefined;
        }
        return t;
    })(),
    WS_TOKEN_MODE: (window.__NOVIY_OVERLAY__?.WS_TOKEN_MODE || "none").trim(),
};

const originHttp = cleanBaseUrl(window.location.origin);
const apiUrl = (p: string) => `/api/${p.replace(/^\//, "")}`;

const headers = (): HeadersInit => {
    const h: Record<string, string> = {};
    if (cfg.OVERLAY_API_TOKEN) {
        h["Authorization"] = cfg.OVERLAY_API_TOKEN.includes(" ")
            ? cfg.OVERLAY_API_TOKEN
            : `Bearer ${cfg.OVERLAY_API_TOKEN}`;
    }
    return h;
};

function _overlayAuthHeader(): string | null {
    if (!cfg.OVERLAY_API_TOKEN) return null;
    return cfg.OVERLAY_API_TOKEN.includes(" ")
        ? cfg.OVERLAY_API_TOKEN
        : `Bearer ${cfg.OVERLAY_API_TOKEN}`;
}

const fetchSpotifyAccessTokenFromBackend = (opts?: { force?: boolean }) =>
    fetchSpotifyAccessTokenFromBackendModule(
        cfg,
        apiUrl,
        _overlayAuthHeader,
        showSpotifyAuthPanel,
        hideSpotifyEmbed,
        setStatus,
        opts
    );

const getSpotifyAccessToken = () => getSpotifyAccessTokenModule(cfg, fetchSpotifyAccessTokenFromBackend);

/**
 * Poll Spotify API for currently playing track and render it.
 * This is the source of truth for what's actually playing on the user's desktop Spotify.
 * The browser does NOT play audio - it only displays track info.
 */
async function pollSpotifyCurrentTrack() {
    try {
        const token = await getSpotifyAccessToken();
        if (!token) return;

        const res = await fetch("https://api.spotify.com/v1/me/player/currently-playing", {
            headers: { Authorization: `Bearer ${token}` },
            cache: "no-store",
        });

        if (res.status === 204 || res.status === 202) {
            // No active playback
            return;
        }

        if (!res.ok) {
            console.warn("overlay: spotify currently-playing failed", res.status);
            return;
        }

        const data = await res.json();
        const item = data?.item;
        if (!item || item.type !== "track") return;

        const trackId = item.id;
        if (!trackId || trackId === currentSpotifyTrackId) return;

        console.log("overlay: spotify track changed", {
            previous: currentSpotifyTrackId,
            current: trackId,
            isPlaying: data?.is_playing,
        });

        currentSpotifyTrackId = trackId;

        const trackName = item.name || "";
        const artists = (item.artists || [])
            .map((a: any) => a?.name || "")
            .filter(Boolean)
            .join(", ");
        const coverUrl = item.album?.images?.[0]?.url || "";

        // Find who added this track from our cache
        const addedBy = trackUserCache.get(trackId);
        let requester = "";
        if (addedBy) {
            try {
                requester = await getUserName(String(addedBy), apiUrl, headers);
            } catch {
                // ignore
            }
        }

        console.log("overlay: rendering track", { trackId, trackName, artists, requester });
        renderTrack({ title: trackName, artists, coverUrl }, requester);
        hideSpotifyEmbed();
    } catch (err) {
        console.warn("overlay: spotify poll failed", err);
    }
}

// Start polling Spotify for current track
let spotifyPollInterval: number | null = null;
function startSpotifyPolling() {
    if (spotifyPollInterval) return;
    // Poll every 2 seconds
    spotifyPollInterval = window.setInterval(pollSpotifyCurrentTrack, 2000);
    // Also poll immediately
    void pollSpotifyCurrentTrack();
}

setupSpotifyAuthButton(cfg, apiUrl, fetchSpotifyAccessTokenFromBackend, showSpotifyAuthPanel, setStatus);

applyAnimation(coverImg);
applyAnimation(photoImg);

// Initialize slot wins module (creates DOM elements for notifications)
initSlotWins();

// Start Spotify polling after a short delay to allow token fetch
setTimeout(() => {
    console.log("overlay: starting spotify polling");
    startSpotifyPolling();
}, 1000);

wsConnect(
    cfg,
    originHttp,
    apiUrl,
    setStatus,
    (photo) => {
        if (photo.id > lastPhotoId) {
            lastPhotoId = photo.id;
            getUserName(String(photo.added_by || ""), apiUrl, headers).then((by) => {
                showPhoto(resolveUrl(originHttp, photo.url), `${photo.name}${by ? ` | by ${by}` : ""}`);
            });
        }
    },
    async (msg) => {
        try {
            // Handle slot_win messages
            if (msg && msg.type === "slot_win") {
                console.log("overlay: received slot_win message via WS");
                await handleSlotWinMessage(msg, apiUrl, headers);
                return;
            }

            if (msg && msg.type === "state") {
                const state = msg as any;
                const version = typeof state.version === "number" ? state.version : 0;
                if (version && version <= lastStateVersion) {
                    return;
                }
                if (version) {
                    lastStateVersion = version;
                }

                // Update track -> user cache from playlist
                const playlist = Array.isArray(state.playlist) ? state.playlist : [];
                for (const track of playlist) {
                    if (track && track.spotify_id && track.added_by) {
                        trackUserCache.set(String(track.spotify_id), Number(track.added_by));
                    }
                }

                // Show/hide track layer based on playing state
                const isPlaying = state.playing === true;
                if (trackLayer) {
                    if (isPlaying) {
                        trackLayer.classList.remove("isHidden");
                    } else {
                        trackLayer.classList.add("isHidden");
                    }
                }

                console.log("overlay: state from backend", {
                    playing: state.playing,
                    index: state.index,
                    playlistLength: playlist.length,
                    version,
                });

                hideSpotifyEmbed();
            }
        } catch (err) {
            console.error("overlay: state handler error", err);
        }
    }
);

void pollPhotosLoop(cfg, apiUrl, headers, originHttp, setStatus);

