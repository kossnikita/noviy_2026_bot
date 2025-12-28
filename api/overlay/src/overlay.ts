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
    enqueueSpotifyTrack as enqueueSpotifyTrackModule,
    spotifyNext as spotifyNextModule,
    getSpotifyCurrentTrackId as getSpotifyCurrentTrackIdModule,
    setSpotifyStateListener as setSpotifyStateListenerModule,
    activateSpotifyElement as activateSpotifyElementModule,
} from "./overlay/spotify_sdk";
import { SpotifyQueueManager } from "./overlay/spotify_queue";

declare global {
    interface Window {
        __NOVIY_OVERLAY__?: Partial<OverlayConfig>;
        onSpotifyWebPlaybackSDKReady?: () => void;
    }
}

let pendingPlayback: PendingPlayback = { kind: "none" };
let lastPhotoId = 0;
let spotifyCurrentTrackId: string | null = null;
let spotifyLastPlayingState = false;
let lastStateVersion = 0;
let spotifyOp: Promise<void> | null = null;

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

function logStateUpdate(state: Record<string, any>, summary: ReturnType<SpotifyQueueManager["summarize"]>, audioUrl: string) {
    console.log("overlay: state update", {
        playing: Boolean(state?.playing),
        spotifyState: state?.spotify_state || null,
        playlistLength: summary.playlistIds.length,
        playlistIndex: summary.playlistIndex,
        spotifyTrackId: summary.spotifyTrackId,
        fallbackTrack: state?.current?.spotify_id || null,
        audioUrl: audioUrl || null,
        pendingPlayback,
        spotifyCurrentTrackId,
        spotifyLastPlayingState,
    });
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

const enqueueSpotifyTrack = (spotifyId: string) =>
    enqueueSpotifyTrackModule(spotifyId, getSpotifyAccessToken);

const spotifyNext = () => spotifyNextModule(getSpotifyAccessToken);
const getSpotifyCurrentTrackId = () => getSpotifyCurrentTrackIdModule(getSpotifyAccessToken);
const setSpotifyStateListener = (listener: ((state: any) => void) | null) =>
    setSpotifyStateListenerModule(listener);
const activateSpotifyElement = () => activateSpotifyElementModule();
const spotifyQueueManager = new SpotifyQueueManager(enqueueSpotifyTrack);

function handleSpotifySdkState(state: any) {
    try {
        const trackId: string | null = state?.track_window?.current_track?.id || null;
        const paused = Boolean(state?.paused);
        if (trackId && trackId !== spotifyCurrentTrackId) {
            console.warn("overlay: sdk track differs from overlay", {
                sdk: trackId,
                overlay: spotifyCurrentTrackId,
                lastStateVersion,
            });
            spotifyCurrentTrackId = trackId;
        }
        // If Spotify is playing but we haven't activated audio yet, show play button
        if (!paused && !spotifyLastPlayingState) {
            console.log("overlay: sdk reports playing, showing play button for audio activation");
            showPlayButton(true, "Enable Audio");
        }
        spotifyLastPlayingState = !paused;
    } catch (err) {
        console.warn("overlay: failed to handle sdk state", err);
    }
}

setSpotifyStateListener(handleSpotifySdkState);

async function runSpotifyOp(fn: () => Promise<void>) {
    if (spotifyOp) {
        try {
            await spotifyOp;
        } catch {
            /* ignore previous op failure */
        }
    }
    const p = (async () => {
        try {
            await fn();
        } finally {
            spotifyOp = null;
        }
    })();
    spotifyOp = p;
    return p;
}

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
        // No pending playback but user clicked - just activate audio and resume if Spotify is playing
        console.log("overlay: no pending playback, resuming spotify if paused");
        try {
            const ready = await initSpotifyPlayerIfNeeded();
            if (ready && spotifyCurrentTrackId) {
                await playSpotifyTrack(spotifyCurrentTrackId);
            }
            showPlayButton(false);
        } catch (err) {
            console.warn("overlay: resume failed", err);
        }
    }
}

if (playButton) {
    playButton.addEventListener("click", () => {
        console.log("overlay: play button clicked, activating audio");
        activateSpotifyElement();
        void tryPlayPendingPlayback();
    });
}

setupSpotifyAuthButton(cfg, apiUrl, fetchSpotifyAccessTokenFromBackend, showSpotifyAuthPanel, setStatus);

applyAnimation(coverImg);
applyAnimation(photoImg);

void fetchSpotifyProfileModule(getSpotifyAccessToken, setStatus);

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
            if (msg && msg.type === "state") {
                const state = msg as any;
                const version = typeof state.version === "number" ? state.version : 0;
                if (version && version <= lastStateVersion) {
                    console.warn("overlay: stale state ignored", { version, lastStateVersion });
                    return;
                }
                if (version) {
                    lastStateVersion = version;
                } else {
                    lastStateVersion += 1;
                }
                const cur = state.current || null;
                if (cur && cur.spotify_id) {
                    try {
                        const meta = await getSpotifyOEmbed(String(cur.spotify_id));
                        const requester = await getUserName(String(cur.added_by || ""), apiUrl, headers);
                        renderTrack(meta, requester);
                    } catch (e) {
                        renderTrack({ title: cur.name || "", artists: cur.artist || "", coverUrl: "" }, "");
                    }
                }

                let audioUrl = cur && cur.url ? String(cur.url) : "";
                if (audioUrl.includes("open.spotify.com/track")) {
                    try {
                        const parsed = new URL(audioUrl);
                        const parts = parsed.pathname.split("/").filter(Boolean);
                        const sid = parts.length ? parts[parts.length - 1] : "";
                        if (sid) {
                            cur.spotify_id = cur.spotify_id || sid;
                            audioUrl = "";
                        }
                    } catch {
                        audioUrl = "";
                    }
                }

                const fallbackSpotifyId = cur && cur.spotify_id ? String(cur.spotify_id) : "";
                const summary = spotifyQueueManager.summarize(state, fallbackSpotifyId);
                const playlistIndex = summary.playlistIndex;
                const spotifyTrackId = summary.spotifyTrackId;
                const nonSequentialJump = Boolean(spotifyTrackId && !summary.sequentialAdvance);
                void prefetchTrackMeta(summary.playlistIds);
                logStateUpdate(state, summary, audioUrl);

                if (audioUrl) {
                    console.log("overlay: audio playlist handling", { playing: state.playing, audioUrl });
                    if (state.playing) {
                        try {
                            await playAudioSrc(audioUrl);
                            showPlayButton(false);
                        } catch (err) {
                            console.error("overlay: audio playback failed", err);
                            pendingPlayback = { kind: "audio", src: audioUrl };
                            showPlayButton(true, "Play");
                        }
                    } else {
                        pauseAudio();
                        pendingPlayback = { kind: "none" };
                        showPlayButton(false);
                    }
                    spotifyQueueManager.reset();
                    console.log("overlay: audio path cleared spotify queue");
                    hideSpotifyEmbed();
                } else if (spotifyTrackId) {
                    try {
                        const ready = await initSpotifyPlayerIfNeeded();
                        if (ready) {
                            if (nonSequentialJump) {
                                console.warn("overlay: non-sequential jump detected, resetting queue", {
                                    playlistIndex,
                                    lastStateVersion,
                                });
                                spotifyQueueManager.reset();
                            }
                            console.log("overlay: spotify path", {
                                playing: state.playing,
                                spotifyTrackId,
                                playlistIndex,
                                spotifyCurrentTrackId,
                                playbackState: state.current?.spotify_state,
                            });
                            let playbackTriggered = false;
                            let playbackFailed = false;
                            let forcePlay = false;
                            if (state.playing) {
                                const actualId = await getSpotifyCurrentTrackId();
                                if (actualId && actualId !== spotifyTrackId) {
                                    console.warn(
                                        "overlay: spotify current track differs from overlay, forcing sync",
                                        { overlay: spotifyTrackId, spotify: actualId }
                                    );
                                    forcePlay = true;
                                    try {
                                        await runSpotifyOp(() => pauseSpotify());
                                        console.log("overlay: paused for resync");
                                        await new Promise(r => setTimeout(r, 300));
                                    } catch (err) {
                                        console.warn("overlay: pause before resync failed", err);
                                    }
                                } else if (actualId) {
                                    spotifyCurrentTrackId = actualId;
                                }
                                console.log("overlay: spotify reported current track", { actualId, forcePlay });
                            }
                            if (state.playing) {
                                const needsPlay =
                                    forcePlay ||
                                    spotifyTrackId !== spotifyCurrentTrackId ||
                                    !spotifyLastPlayingState;
                                console.log("overlay: compute needsPlay", { needsPlay, forcePlay, spotifyTrackId, spotifyCurrentTrackId, lastState: spotifyLastPlayingState });
                                if (needsPlay) {
                                    const shouldNext = spotifyQueueManager.shouldUseNext(summary);
                                    console.log("overlay: spotify transition", { shouldUseNext: shouldNext, forcePlay });
                                    try {
                                        if (shouldNext && !forcePlay) {
                                            await runSpotifyOp(() => spotifyNext());
                                            console.log("overlay: called spotifyNext to advance", { spotifyTrackId });
                                        } else {
                                            if (forcePlay) {
                                                console.log("overlay: forced play detected, resetting queue for fresh preload", {
                                                    spotifyTrackId,
                                                    playlistIndex,
                                                });
                                                spotifyQueueManager.reset();
                                            }
                                            await runSpotifyOp(() => playSpotifyTrack(spotifyTrackId));
                                            console.log("overlay: called playSpotifyTrack", { spotifyTrackId });
                                        }
                                        pendingPlayback = { kind: "none" };
                                        showPlayButton(false);
                                        playbackTriggered = true;
                                    } catch (err) {
                                        console.error("overlay: spotify playback trigger failed", err);
                                        playbackFailed = true;
                                        pendingPlayback = { kind: "spotify", spotifyId: spotifyTrackId };
                                        showPlayButton(true, "Play");
                                    }
                                }
                            } else if (spotifyLastPlayingState) {
                                console.log("overlay: spotify reported stop, issuing pause");
                                await runSpotifyOp(() => pauseSpotify());
                                pendingPlayback = { kind: "none" };
                                showPlayButton(false);
                            }

                            if (state.playing && !playbackFailed) {
                                spotifyLastPlayingState = true;
                                spotifyCurrentTrackId = spotifyTrackId;
                            } else if (!state.playing) {
                                spotifyLastPlayingState = false;
                                spotifyCurrentTrackId = null;
                            }

                            if (!playbackFailed && spotifyTrackId) {
                                if (!forcePlay) {
                                    spotifyQueueManager.consume(spotifyTrackId);
                                }
                                if (playlistIndex >= 0) {
                                    console.log("overlay: spotify preloading future tracks", {
                                        playlistIndex,
                                        playlistIds: summary.playlistIds.length,
                                        isResync: forcePlay,
                                    });
                                    await spotifyQueueManager.preload(summary);
                                }
                            }

                            if (playbackTriggered) {
                                spotifyCurrentTrackId = spotifyTrackId;
                            }

                            hideSpotifyEmbed();
                        } else {
                            console.warn("overlay: spotify player not ready", { playing: state.playing });
                            hideSpotifyEmbed();
                            if (state.playing) {
                                pendingPlayback = { kind: "spotify", spotifyId: spotifyTrackId };
                                showPlayButton(true, "Play");
                            } else {
                                pendingPlayback = { kind: "none" };
                                showPlayButton(false);
                            }
                            if (!state.playing) pauseAudio();
                        }
                    } catch (err) {
                        console.error("overlay: spotify handler threw", err, {
                            spotifyTrackId,
                            playing: state.playing,
                            playlistIndex,
                        });
                        hideSpotifyEmbed();
                        if (state.playing) {
                            pendingPlayback = { kind: "spotify", spotifyId: spotifyTrackId };
                            showPlayButton(true, "Play");
                        } else {
                            pendingPlayback = { kind: "none" };
                            showPlayButton(false);
                        }
                    }
                } else {
                    spotifyQueueManager.reset();
                    pauseAudio();
                    hideSpotifyEmbed();
                    pendingPlayback = { kind: "none" };
                    showPlayButton(false);
                }
            }
        } catch (err) {
            console.error("overlay: error processing state message", err);
        }
    }
);

void pollQueueLoop(cfg, apiUrl, headers, setStatus);
void pollPhotosLoop(cfg, apiUrl, headers, originHttp, setStatus);
