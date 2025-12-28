import { cleanBaseUrl, resolveUrl } from "./utils";
import { OverlayConfig } from "./overlay/types";
import { playAudioSrc, pauseAudio } from "./overlay/audio";
import { coverImg, photoImg, statusEl } from "./overlay/dom";
import { PendingPlayback } from "./overlay/spotify_types";
import { applyAnimation } from "./overlay/dom_helpers";
import { getUserName, getSpotifyOEmbed, prefetchTrackMeta } from "./overlay/overlay_helpers";
import { wsConnect } from "./overlay/ws";
import { renderTrack } from "./overlay/track_render";
import { pollQueueLoop, pollPhotosLoop } from "./overlay/overlay_loops";
import { showPhoto } from "./overlay/photo_helpers";
import {
    hideSpotifyEmbed,
    showSpotifyAuthPanel,
    setupSpotifyAuthButton,
} from "./overlay/spotify_auth";
import {
    fetchSpotifyAccessTokenFromBackend as fetchSpotifyAccessTokenFromBackendModule,
    fetchSpotifyProfile as fetchSpotifyProfileModule,
    getSpotifyAccessToken as getSpotifyAccessTokenModule,
    initSpotifyPlayerIfNeeded as initSpotifyPlayerIfNeededModule,
    spotifyPause as spotifyPauseModule,
    spotifyPlayTrack as spotifyPlayTrackModule,
    setSpotifyStateListener as setSpotifyStateListenerModule,
    activateSpotifyElement as activateSpotifyElementModule,
    getSpotifyDeviceId as getSpotifyDeviceIdModule,
} from "./overlay/spotify_sdk";

declare global {
    interface Window {
        __NOVIY_OVERLAY__?: Partial<OverlayConfig>;
        onSpotifyWebPlaybackSDKReady?: () => void;
    }
}

let pendingPlayback: PendingPlayback = { kind: "none" };
let lastPhotoId = 0;
let spotifyCurrentTrackId: string | null = null;
let lastStateVersion = 0;
let wsClient: { send: (msg: any) => void } | null = null;

// Cache of spotify_id -> added_by user ID from backend playlist
let trackUserCache: Map<string, number> = new Map();

// Audio activation flag - browsers require user gesture to enable audio
let audioActivated = false;

const playButton = (() => {
    try {
        const button = document.createElement("button");
        button.id = "noviy-play-button";
        button.textContent = "Play";
        button.classList.add("overlay-play-button");
        document.body.appendChild(button);
        return button;
    } catch (e) {
        console.warn("overlay: failed to create play button", e);
        return null;
    }
})();

function showPlayButton(visible: boolean, label?: string) {
    if (!playButton) return;
    if (label) playButton.textContent = label;
    playButton.style.display = visible ? "block" : "none";
}

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

const initSpotifyPlayerIfNeeded = () =>
    initSpotifyPlayerIfNeededModule(cfg, getSpotifyAccessToken, setStatus);

const playSpotifyTrack = (spotifyId: string) =>
    spotifyPlayTrackModule(spotifyId, getSpotifyAccessToken, setStatus);

const pauseSpotify = () => spotifyPauseModule(getSpotifyAccessToken);

const setSpotifyStateListener = (listener: ((state: any) => void) | null) =>
    setSpotifyStateListenerModule(listener);
const activateSpotifyElement = () => activateSpotifyElementModule();

/**
 * SDK-driven track rendering.
 * When Spotify SDK reports a new track, we render it directly.
 * This is the source of truth for what's actually playing.
 */
async function handleSpotifySdkState(state: any) {
    try {
        const currentTrack = state?.track_window?.current_track;
        const trackId: string | null = currentTrack?.id || null;
        const paused = Boolean(state?.paused);
        
        if (!trackId) {
            console.log("overlay: sdk state has no current track");
            return;
        }
        
        // Only update if track changed
        if (trackId === spotifyCurrentTrackId) {
            return;
        }
        
        console.log("overlay: sdk track changed", {
            previous: spotifyCurrentTrackId,
            current: trackId,
            paused,
        });
        
        spotifyCurrentTrackId = trackId;
        
        // Extract track info from SDK state
        const trackName = currentTrack?.name || "";
        const artists = (currentTrack?.artists || [])
            .map((a: any) => a?.name || "")
            .filter(Boolean)
            .join(", ");
        const coverUrl = currentTrack?.album?.images?.[0]?.url || "";
        
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
        
        console.log("overlay: rendering track from SDK", {
            trackId,
            trackName,
            artists,
            requester,
        });
        
        renderTrack(
            { title: trackName, artists, coverUrl },
            requester
        );
        
        hideSpotifyEmbed();
    } catch (err) {
        console.warn("overlay: failed to handle sdk state", err);
    }
}

setSpotifyStateListener(handleSpotifySdkState);

async function tryPlayPendingPlayback() {
    // Always try to activate Spotify element on user gesture
    activateSpotifyElement();
    const current = pendingPlayback;
    if (current.kind === "audio") {
        try {
            await playAudioSrc(current.src);
            pendingPlayback = { kind: "none" };
            showPlayButton(false);
        } catch (err) {
            console.warn("overlay: retrying audio playback failed", err);
        }
    } else if (current.kind === "spotify") {
        try {
            const ready = await initSpotifyPlayerIfNeeded();
            if (!ready) return;
            await playSpotifyTrack(current.spotifyId);
            pendingPlayback = { kind: "none" };
            showPlayButton(false);
        } catch (err) {
            console.warn("overlay: retrying spotify playback failed", err);
        }
    } else {
        // No pending playback - just activate SDK audio context
        console.log("overlay: activating spotify audio context");
        showPlayButton(false);
    }
}

// Auto-activate audio on user interaction (fallback for browsers with autoplay restrictions)
function autoActivateAudio() {
    if (!audioActivated) {
        console.log("overlay: auto-activating audio on user gesture");
        activateSpotifyElement();
        audioActivated = true;
    }
}

// Listen for user interactions to activate audio (fallback)
document.addEventListener("click", autoActivateAudio, { once: true });
document.addEventListener("keydown", autoActivateAudio, { once: true });
document.addEventListener("touchstart", autoActivateAudio, { once: true });

setupSpotifyAuthButton(cfg, apiUrl, fetchSpotifyAccessTokenFromBackend, showSpotifyAuthPanel, setStatus);

applyAnimation(coverImg);
applyAnimation(photoImg);

void fetchSpotifyProfileModule(getSpotifyAccessToken, setStatus);

wsClient = wsConnect(
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
            if (msg && msg.type === "state") {
                const state = msg as any;
                const version = typeof state.version === "number" ? state.version : 0;
                if (version && version <= lastStateVersion) {
                    console.log("overlay: stale state ignored", { version, lastStateVersion });
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
                
                console.log("overlay: state update from backend", {
                    playing: state.playing,
                    index: state.index,
                    playlistLength: playlist.length,
                    version,
                });
                
                // Initialize Spotify player if needed
                const ready = await initSpotifyPlayerIfNeeded();
                if (!ready) {
                    console.warn("overlay: spotify player not ready");
                    // Show play button to allow user to activate
                    if (state.playing) {
                        const cur = state.current;
                        if (cur && cur.spotify_id) {
                            pendingPlayback = { kind: "spotify", spotifyId: cur.spotify_id };
                            showPlayButton(true, "Play");
                        }
                    }
                } else {
                    // SDK is ready - activate audio and register device
                    if (!audioActivated) {
                        console.log("overlay: auto-activating audio after SDK ready");
                        activateSpotifyElement();
                        audioActivated = true;
                    }
                    
                    // Send device_id to backend for playback control
                    const deviceId = getSpotifyDeviceIdModule();
                    if (deviceId && wsClient) {
                        console.log("overlay: registering device_id with backend", deviceId);
                        wsClient.send({ op: "register_device", device_id: deviceId });
                    }
                }
                
                hideSpotifyEmbed();
            }
        } catch (err) {
            console.error("overlay: error processing state message", err);
        }
    }
);

void pollQueueLoop(cfg, apiUrl, headers, setStatus);
void pollPhotosLoop(cfg, apiUrl, headers, originHttp, setStatus);
