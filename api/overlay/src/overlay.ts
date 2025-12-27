type OverlayConfig = {
    OVERLAY_API_TOKEN: string;
    WS_URL: string;
    PHOTO_POLL_INTERVAL_MS: number;
    PHOTO_DISPLAY_MS: number;
    QUEUE_POLL_INTERVAL_MS: number;
    SPOTIFY_OAUTH_TOKEN?: string;
    WS_TOKEN_MODE: string;
};

import {
    clampNum,
    cleanBaseUrl,
    pickRequesterId,
    pickTrackId,
    resolveUrl,
    wsFromHttp,
} from "./utils";

declare global {
    interface Window {
        __NOVIY_OVERLAY__?: Partial<OverlayConfig>;
    }
}

type QueueItem = import("./utils").QueueItem;

type Photo = {
    id: number;
    name: string;
    url: string;
    added_by: number;
    added_at: string;
};

type User = {
    id?: string | number;
    username?: string;
    first_name?: string;
    last_name?: string;
    display_name?: string;
    name?: string;
};

type TrackMeta = {
    title: string;
    artists: string;
    coverUrl: string;
};

const el = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

const titleEl = el<HTMLDivElement>("title");
const artistsEl = el<HTMLDivElement>("artists");
const albumEl = el<HTMLDivElement>("album");
const requestedByEl = el<HTMLDivElement>("requestedBy");
const coverImg = el<HTMLImageElement>("coverImg");
const statusEl = el<HTMLDivElement>("status");

const photoLayer = el<HTMLDivElement>("photoLayer");
const photoImg = el<HTMLImageElement>("photoImg");
const photoCaption = el<HTMLDivElement>("photoCaption");

// Audio player element (hidden). Prefer direct audio URL if provided by server.
const audioEl = (() => {
    try {
        const a = document.createElement("audio");
        a.id = "noviy-audio";
        a.preload = "auto";
        a.style.display = "none";
        a.crossOrigin = "anonymous";
        document.body.appendChild(a);
        a.addEventListener("play", () => console.log("overlay: audio play event"));
        a.addEventListener("pause", () => console.log("overlay: audio pause event"));
        a.addEventListener("error", (e) => console.error("overlay: audio error", e));
        return a;
    } catch (e) {
        console.warn("overlay: failed to create audio element", e);
        return null as unknown as HTMLAudioElement;
    }
})();

// Play button to satisfy user gesture requirements when autoplay is blocked
const playButton = (() => {
    try {
        const b = document.createElement("button");
        b.id = "noviy-play-button";
        b.textContent = "Play audio";
        b.style.position = "fixed";
        b.style.right = "16px";
        b.style.bottom = "16px";
        b.style.zIndex = "9999";
        b.style.padding = "10px 14px";
        b.style.borderRadius = "8px";
        b.style.background = "rgba(0,0,0,0.6)";
        b.style.color = "white";
        b.style.border = "none";
        b.style.cursor = "pointer";
        b.style.display = "none";
        document.body.appendChild(b);
        return b;
    } catch (e) {
        return null as unknown as HTMLButtonElement;
    }
})();

function showPlayButton(visible: boolean) {
    if (!playButton) return;
    playButton.style.display = visible ? "block" : "none";
}

async function userGesturePlay() {
    if (!audioEl) return;
    try {
        await audioEl.play();
        console.log("overlay: user-initiated play succeeded");
        showPlayButton(false);
    } catch (e) {
        console.error("overlay: user-initiated play failed", e);
    }
}
if (playButton) playButton.addEventListener("click", () => void userGesturePlay());

// Spotify embed iframe (used as a fallback when only spotify_id is available)
let spotifyIframe: HTMLIFrameElement | null = null;
function ensureSpotifyIframe() {
    if (spotifyIframe) return spotifyIframe;
    try {
        spotifyIframe = document.createElement("iframe");
        spotifyIframe.id = "noviy-spotify-embed";
        spotifyIframe.style.display = "none";
        spotifyIframe.style.border = "0";
        spotifyIframe.width = "300";
        spotifyIframe.height = "80";
        spotifyIframe.allow = "autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture";
        const trackLayer = el<HTMLDivElement>("trackLayer");
        trackLayer.appendChild(spotifyIframe);
        return spotifyIframe;
    } catch (e) {
        console.warn("overlay: failed to create spotify iframe", e);
        spotifyIframe = null;
        return spotifyIframe;
    }
}

// --- Spotify authorization UI (when backend says "Spotify is not connected") ---
const spotifyAuthPanel = (() => {
    try {
        const wrap = document.createElement("div");
        wrap.id = "noviy-spotify-auth";
        wrap.style.position = "fixed";
        wrap.style.right = "16px";
        wrap.style.bottom = "64px";
        wrap.style.zIndex = "9999";
        wrap.style.maxWidth = "360px";
        wrap.style.padding = "10px 12px";
        wrap.style.borderRadius = "10px";
        wrap.style.background = "rgba(0,0,0,0.6)";
        wrap.style.color = "white";
        wrap.style.fontSize = "14px";
        wrap.style.display = "none";

        const msg = document.createElement("div");
        msg.id = "noviy-spotify-auth-msg";
        msg.textContent = "Spotify is not connected.";
        msg.style.marginBottom = "8px";
        wrap.appendChild(msg);

        const btn = document.createElement("button");
        btn.id = "noviy-spotify-auth-button";
        btn.textContent = "Authorize Spotify";
        btn.style.padding = "10px 14px";
        btn.style.borderRadius = "8px";
        btn.style.background = "rgba(255,255,255,0.12)";
        btn.style.color = "white";
        btn.style.border = "1px solid rgba(255,255,255,0.18)";
        btn.style.cursor = "pointer";
        wrap.appendChild(btn);

        document.body.appendChild(wrap);
        return { wrap, msg, btn };
    } catch (e) {
        console.warn("overlay: failed to create spotify auth panel", e);
        return null as unknown as { wrap: HTMLDivElement; msg: HTMLDivElement; btn: HTMLButtonElement };
    }
})();

let spotifyAuthPollTimer: number | null = null;

function showSpotifyAuthPanel(visible: boolean, message?: string) {
    if (!spotifyAuthPanel) return;
    if (message) spotifyAuthPanel.msg.textContent = message;
    spotifyAuthPanel.wrap.style.display = visible ? "block" : "none";
    if (!visible && spotifyAuthPollTimer) {
        window.clearInterval(spotifyAuthPollTimer);
        spotifyAuthPollTimer = null;
    }
}

function spotifyLoginUrl(): string | null {
    const t = (cfg.OVERLAY_API_TOKEN || "").trim();
    if (!t) return null;
    // Use query token because browser navigation can't set Authorization headers.
    const u = new URL(apiUrl("spotify/login"), window.location.origin);
    u.searchParams.set("token", t);
    return u.toString();
}

async function spotifyAuthPollUntilConnected() {
    if (spotifyAuthPollTimer) return;
    spotifyAuthPollTimer = window.setInterval(() => {
        void fetchSpotifyAccessTokenFromBackend({ force: true })
            .then((t) => {
                if (t) {
                    showSpotifyAuthPanel(false);
                    setStatus("spotify: connected");
                }
            })
            .catch(() => {
                // keep polling; errors are expected until user finishes OAuth
            });
    }, 3000);
}

if (spotifyAuthPanel) {
    spotifyAuthPanel.btn.addEventListener("click", () => {
        const u = spotifyLoginUrl();
        if (!u) {
            showSpotifyAuthPanel(true, "Missing OVERLAY_API_TOKEN. Set it in overlay config.");
            return;
        }

        // Use noopener/noreferrer to avoid leaking token via referrer.
        try {
            window.open(u, "_blank", "noopener,noreferrer");
        } catch {
            // Fallback: same-tab navigation.
            window.location.href = u;
            return;
        }

        showSpotifyAuthPanel(true, "Complete Spotify login in the opened tab, then return here.");
        void spotifyAuthPollUntilConnected();
    });
}

async function playAudioSrc(src: string) {
    if (!audioEl) return;
    try {
        if (audioEl.src !== src) {
            audioEl.src = src;
            audioEl.load();
        }
        await audioEl.play();
        console.log("overlay: playing audio src", src);
    } catch (e) {
        console.warn("overlay: audio play failed", e);
        throw e;
    }
}

function pauseAudio() {
    if (!audioEl) return;
    try {
        audioEl.pause();
        console.log("overlay: audio paused");
    } catch (e) {
        console.warn("overlay: audio pause failed", e);
    }
}

function showSpotifyEmbed(spotifyId: string | undefined, visible: boolean) {
    if (!spotifyId) {
        if (spotifyIframe) spotifyIframe.style.display = "none";
        return;
    }
    const iframe = ensureSpotifyIframe();
    if (!iframe) return;
    iframe.src = `https://open.spotify.com/embed/track/${encodeURIComponent(spotifyId)}`;
    iframe.style.display = visible ? "block" : "none";
    console.log("overlay: spotify embed set", spotifyId, { visible });
}

// --- Spotify Web Playback SDK integration ---
let spotifyPlayer: any = null;
let spotifyDeviceId: string | null = null;
let spotifySdkLoaded = false;

let spotifyAccessToken: string | null = null;
let spotifyAccessTokenExpiresAt: number = 0;
let spotifyTokenLastAttemptAt = 0;

function loadSpotifySdk(): Promise<void> {
    if ((window as any).Spotify) {
        spotifySdkLoaded = true;
        return Promise.resolve();
    }
    return new Promise((resolve, reject) => {
        const s = document.createElement("script");
        s.src = "https://sdk.scdn.co/spotify-player.js";
        s.async = true;
        s.onload = () => {
            spotifySdkLoaded = true;
            resolve();
        };
        s.onerror = (e) => reject(e);
        document.head.appendChild(s);
    });
}

async function initSpotifyPlayerIfNeeded() {
    const token = await getSpotifyAccessToken();
    if (!token) return false;
    if (spotifyPlayer && spotifyDeviceId) return true;
    try {
        await loadSpotifySdk();
    } catch (e) {
        console.error("overlay: failed to load spotify sdk", e);
        return false;
    }

    return new Promise<boolean>((resolve) => {
        try {
            spotifyPlayer = new (window as any).Spotify.Player({
                name: "Noviy Overlay",
                getOAuthToken: (cb: (t: string) => void) => {
                    void getSpotifyAccessToken()
                        .then((t) => cb(t || ""))
                        .catch(() => cb(""));
                },
                volume: 0.8,
            });

            spotifyPlayer.addListener("ready", ({ device_id }: any) => {
                spotifyDeviceId = device_id;
                console.log("overlay: spotify player ready", device_id);
                setStatus("spotify: ready");
                resolve(true);
            });

            spotifyPlayer.addListener("not_ready", ({ device_id }: any) => {
                console.warn("overlay: spotify device not ready", device_id);
                setStatus("spotify: not ready");
            });

            spotifyPlayer.addListener("initialization_error", (e: any) => console.error("overlay: spotify init error", e));
            spotifyPlayer.addListener("authentication_error", (e: any) => console.error("overlay: spotify auth error", e));
            spotifyPlayer.addListener("account_error", (e: any) => console.error("overlay: spotify account error", e));

            spotifyPlayer.connect().then((connected: boolean) => {
                console.log("overlay: spotify connect result", connected);
                if (!connected) setStatus("spotify: connect failed");
            });
        } catch (e) {
            console.error("overlay: spotify init failed", e);
            resolve(false);
        }
    });
}

async function spotifyApiRequest(path: string, method = "PUT", body?: any) {
    const token = await getSpotifyAccessToken();
    if (!token) throw new Error("Missing Spotify access token");
    const url = `https://api.spotify.com/v1${path}`;
    const r = await fetch(url, {
        method,
        headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
        },
        body: body ? JSON.stringify(body) : undefined,
    });
    if (!r.ok) {
        const text = await r.text();
        throw new Error(`Spotify API ${r.status}: ${text}`);
    }
    return r;
}

function _overlayAuthHeader(): string | null {
    const raw = (cfg.OVERLAY_API_TOKEN || "").trim();
    if (!raw) return null;
    return raw.includes(" ") ? raw : `Bearer ${raw}`;
}

async function fetchSpotifyAccessTokenFromBackend(opts?: { force?: boolean }): Promise<string | null> {
    // Avoid hammering the backend in case it's not configured.
    const now = Date.now();
    if (!opts?.force && now - spotifyTokenLastAttemptAt < 60_000) return spotifyAccessToken;
    spotifyTokenLastAttemptAt = now;

    const auth = _overlayAuthHeader();
    if (!auth) {
        console.error("overlay: cannot fetch spotify token (missing OVERLAY_API_TOKEN)");
        return null;
    }

    try {
        const r = await fetch(apiUrl("spotify/token"), {
            method: "GET",
            headers: { Authorization: auth },
            cache: "no-store",
        });
        if (!r.ok) {
            const text = await r.text();
            if (r.status === 409) {
                // This is the "not connected" state; prompt user to authorize.
                let detail = "Spotify is not connected. Open /spotify/login to authorize.";
                try {
                    const j = JSON.parse(text);
                    if (j && typeof j.detail === "string") detail = j.detail;
                } catch {
                    // ignore parse errors
                }
                showSpotifyAuthPanel(true, detail);
            } else if (r.status === 401 || r.status === 403) {
                showSpotifyAuthPanel(true, "Spotify auth requires a valid OVERLAY_API_TOKEN.");
            }
            console.warn("overlay: backend spotify token fetch failed", r.status, text);
            return null;
        }
        const data = (await r.json()) as any;
        const token = String(data?.access_token || "").trim();
        const exp = Number(data?.expires_at || 0);
        if (!token) {
            console.warn("overlay: backend spotify token response missing access_token");
            return null;
        }
        spotifyAccessToken = token;
        spotifyAccessTokenExpiresAt = exp ? exp * 1000 : 0;
        console.log("overlay: spotify token obtained from backend", {
            expires_at: exp || null,
        });
        // If token is now available, hide auth panel (if shown)
        showSpotifyAuthPanel(false);
        return token;
    } catch (e) {
        console.warn("overlay: backend spotify token request error", e);
        return null;
    }
}

async function getSpotifyAccessToken(): Promise<string | null> {
    // 1) If explicitly provided in env/runtime config, use it.
    if (cfg.SPOTIFY_OAUTH_TOKEN) return cfg.SPOTIFY_OAUTH_TOKEN;

    // 2) If we already fetched a backend token and it's not near-expiry, use it.
    const now = Date.now();
    if (spotifyAccessToken && spotifyAccessTokenExpiresAt) {
        if (now < spotifyAccessTokenExpiresAt - 30_000) return spotifyAccessToken;
    }

    // 3) Fetch/refresh from backend.
    return await fetchSpotifyAccessTokenFromBackend();
}

// Fetch Spotify profile once on load to log subscription/product type
async function fetchSpotifyProfile() {
    const token = await getSpotifyAccessToken();
    if (!token) return;
    try {
        const r = await fetch("https://api.spotify.com/v1/me", {
            method: "GET",
            headers: {
                Authorization: `Bearer ${token}`,
                "Content-Type": "application/json",
            },
        });
        if (!r.ok) {
            console.warn("overlay: spotify /me fetch failed", r.status);
            return;
        }
        const data = await r.json();
        const product = (data && data.product) ? String(data.product) : "unknown";
        console.log("overlay: spotify profile", { id: data.id, display_name: data.display_name, product: product, country: data.country });
        setStatus(`spotify: ${product}`);
    } catch (e) {
        console.error("overlay: spotify /me request error", e);
    }
}

async function spotifyPlayTrack(spotifyId: string) {
    if (!spotifyDeviceId) {
        await initSpotifyPlayerIfNeeded();
        if (!spotifyDeviceId) throw new Error("No spotify device id");
    }

    // Ensure the Spotify Connect device is active/selected for playback.
    // Without this, play calls may fail if another device is currently active.
    try {
        await spotifyApiRequest("/me/player", "PUT", {
            device_ids: [spotifyDeviceId],
            play: false,
        });
        console.log("overlay: spotify transferred playback to device", spotifyDeviceId);
    } catch (e) {
        console.warn("overlay: spotify transfer playback failed", e);
    }

    const uri = `spotify:track:${spotifyId}`;
    await spotifyApiRequest(`/me/player/play?device_id=${encodeURIComponent(spotifyDeviceId!)}`, "PUT", { uris: [uri] });
    console.log("overlay: spotify play", spotifyId);
}

async function spotifyPause() {
    if (!spotifyDeviceId) return;
    await spotifyApiRequest(`/me/player/pause?device_id=${encodeURIComponent(spotifyDeviceId)}`, "PUT");
    console.log("overlay: spotify pause");
}

async function spotifyNext() {
    if (!spotifyDeviceId) return;
    await spotifyApiRequest(`/me/player/next?device_id=${encodeURIComponent(spotifyDeviceId)}`, "POST");
    console.log("overlay: spotify next");
}

async function spotifyPrev() {
    if (!spotifyDeviceId) return;
    await spotifyApiRequest(`/me/player/previous?device_id=${encodeURIComponent(spotifyDeviceId)}`, "POST");
    console.log("overlay: spotify prev");
}


function setStatus(text: string) {
    statusEl.textContent = text;
}

const cfg: OverlayConfig = {
    OVERLAY_API_TOKEN: (window.__NOVIY_OVERLAY__?.OVERLAY_API_TOKEN || "").trim(),
    WS_URL: (window.__NOVIY_OVERLAY__?.WS_URL || "").trim(),
    PHOTO_POLL_INTERVAL_MS: Number(window.__NOVIY_OVERLAY__?.PHOTO_POLL_INTERVAL_MS ?? 2000),
    PHOTO_DISPLAY_MS: Number(window.__NOVIY_OVERLAY__?.PHOTO_DISPLAY_MS ?? 10000),
    QUEUE_POLL_INTERVAL_MS: Number(window.__NOVIY_OVERLAY__?.QUEUE_POLL_INTERVAL_MS ?? 2000),
    // Load Spotify token from several "env-like" sources to support build-time or server injection.
    SPOTIFY_OAUTH_TOKEN: (function loadSpotifyToken(): string | undefined {
        // 1) Runtime injected overlay config
        let t = (window.__NOVIY_OVERLAY__?.SPOTIFY_OAUTH_TOKEN || "") as string;

        // 2) Optional global env object or direct global var (set by server/template/build)
        if (!t) t = (window as any).__NOVIY_ENV__?.SPOTIFY_OAUTH_TOKEN || (window as any).SPOTIFY_OAUTH_TOKEN || "";

        // 3) Meta tag in document head (useful for server-side templates)
        if (!t) {
            try {
                const m = document.querySelector('meta[name="SPOTIFY_OAUTH_TOKEN"]') as HTMLMetaElement | null;
                if (m && m.content) t = m.content;
            } catch {
                // ignore DOM errors
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

// Overlay and API are served from the same origin.
// In the default nginx setup, the API is exposed under the /api/ prefix.
const originHttp = cleanBaseUrl(window.location.origin);
const apiUrl = (p: string) => `/api/${p.replace(/^\//, '')}`;

const headers = (): HeadersInit => {
    const h: Record<string, string> = {};
    if (cfg.OVERLAY_API_TOKEN) {
        // If token already includes scheme, keep; else use Bearer.
        h["Authorization"] = cfg.OVERLAY_API_TOKEN.includes(" ") ? cfg.OVERLAY_API_TOKEN : `Bearer ${cfg.OVERLAY_API_TOKEN}`;
    }
    return h;
};

function applyAnimation(img: HTMLImageElement) {
    img.classList.remove("anim-kenburns");
    img.classList.add("anim-kenburns");
}

function safeSetImage(img: HTMLImageElement, src: string) {
    const s = (src || "").trim();
    if (!s) {
        img.removeAttribute("src");
        return;
    }
    if (img.src === s) return;
    img.decoding = "async";
    img.loading = "eager";
    img.src = s;
}

// Caches
const userNameCache = new Map<string, string>();
const trackCache = new Map<string, TrackMeta>();

async function fetchJson(url: string) {
    const r = await fetch(url, { headers: headers(), cache: "no-store" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
}

async function getUserName(userId: string): Promise<string> {
    const key = userId.trim();
    if (!key) return "";
    const cached = userNameCache.get(key);
    if (cached) return cached;

    try {
        const data = (await fetchJson(apiUrl(`users/${encodeURIComponent(key)}`))) as User;
        const username = (data.display_name || data.username || data.name || "").trim();
        const first = (data.first_name || "").trim();
        const last = (data.last_name || "").trim();
        const full = `${first} ${last}`.trim();
        const resolved = username || full || key;
        userNameCache.set(key, resolved);
        return resolved;
    } catch {
        userNameCache.set(key, key);
        return key;
    }
}

async function getSpotifyOEmbed(trackId: string): Promise<TrackMeta> {
    const id = trackId.trim();
    const cached = trackCache.get(id);
    if (cached) return cached;

    // Spotify oEmbed is the only way to get cover/title from a browser without Spotify auth.
    // It usually works with CORS.
    const url = `https://open.spotify.com/oembed?url=spotify:track:${encodeURIComponent(id)}`;
    const r = await fetch(url, { cache: "force-cache" });
    if (!r.ok) {
        const fallback = { title: id, artists: "", coverUrl: "" };
        trackCache.set(id, fallback);
        return fallback;
    }
    const data = (await r.json()) as any;

    const rawTitle = String(data?.title || id);
    const thumb = String(data?.thumbnail_url || "");

    // Common format: "Track Name - Artist". Keep split best-effort.
    let t = rawTitle;
    let a = "";
    const idx = rawTitle.lastIndexOf(" - ");
    if (idx > 0) {
        t = rawTitle.slice(0, idx).trim();
        a = rawTitle.slice(idx + 3).trim();
    }

    const meta = { title: t || id, artists: a, coverUrl: thumb };
    trackCache.set(id, meta);
    return meta;
}

function renderTrack(meta: TrackMeta, requestedBy: string) {
    console.log("overlay: renderTrack", { title: meta.title, artists: meta.artists, coverUrl: meta.coverUrl, requestedBy });
    titleEl.textContent = meta.title || "Idle";
    artistsEl.textContent = meta.artists || "";
    albumEl.textContent = "";
    requestedByEl.textContent = requestedBy ? `Requested by: ${requestedBy}` : "";

    safeSetImage(coverImg, meta.coverUrl);
    applyAnimation(coverImg);
}

let lastTrackId = "";
let lastRequester = "";

async function pollQueueLoop() {
    while (true) {
        try {
            const data = await fetchJson(apiUrl("spotify-tracks?limit=200&offset=0"));
            const arr = Array.isArray(data) ? (data as QueueItem[]) : [];
            const first = arr[0];

            if (!first) {
                lastTrackId = "";
                lastRequester = "";
                renderTrack({ title: "Idle", artists: "", coverUrl: "" }, "");
            } else {
                const trackId = pickTrackId(first);
                const requesterId = pickRequesterId(first);

                if (trackId && (trackId !== lastTrackId || requesterId !== lastRequester)) {
                    lastTrackId = trackId;
                    lastRequester = requesterId;

                    const [meta, reqName] = await Promise.all([
                        getSpotifyOEmbed(trackId),
                        getUserName(requesterId),
                    ]);
                    renderTrack(meta, reqName);
                }
            }

            setStatus("ok");
        } catch (e) {
            setStatus("queue: error");
        }

        await new Promise((r) => setTimeout(r, clampNum(cfg.QUEUE_POLL_INTERVAL_MS, 500, 30000)));
    }
}

let lastPhotoId = 0;
let photoHideTimer: number | null = null;

function showPhoto(url: string, caption: string) {
    safeSetImage(photoImg, url);
    applyAnimation(photoImg);
    photoCaption.textContent = caption;

    photoLayer.classList.remove("isHidden");
    if (photoHideTimer) window.clearTimeout(photoHideTimer);
    photoHideTimer = window.setTimeout(() => {
        photoLayer.classList.add("isHidden");
    }, clampNum(cfg.PHOTO_DISPLAY_MS, 0, 600000));
}

async function pollPhotosLoop() {
    // Initialize cursor to current max (do not replay history)
    try {
        const init = await fetchJson(apiUrl("photos?limit=100&offset=0"));
        if (Array.isArray(init)) {
            for (const p of init as any[]) {
                const id = Number(p?.id || 0);
                if (id > lastPhotoId) lastPhotoId = id;
            }
        }
    } catch {
        // ignore
    }

    while (true) {
        try {
            const url = apiUrl(`photos?limit=100&offset=0&after_id=${encodeURIComponent(String(lastPhotoId))}`);
            const data = await fetchJson(url);
            const arr = Array.isArray(data) ? (data as Photo[]) : [];

            if (arr.length) {
                // show sequentially; newest last
                arr.sort((a, b) => (a.id || 0) - (b.id || 0));
                for (const p of arr) {
                    if ((p.id || 0) <= lastPhotoId) continue;
                    lastPhotoId = p.id;

                    const by = await getUserName(String(p.added_by || ""));
                    const caption = `${p.name || "Photo"}${by ? ` | by ${by}` : ""}`;
                    showPhoto(resolveUrl(originHttp, p.url), caption);

                    // Space out if multiple photos arrive at once
                    await new Promise((r) => setTimeout(r, clampNum(cfg.PHOTO_DISPLAY_MS, 0, 600000) + 150));
                }
            }
        } catch {
            // ignore
        }

        await new Promise((r) => setTimeout(r, clampNum(cfg.PHOTO_POLL_INTERVAL_MS, 500, 30000)));
    }
}

// Optional WebSocket: receives events (if your server pushes state/photos)
function withWsToken(url: string) {
    const mode = (cfg.WS_TOKEN_MODE || "none").trim();
    if (!cfg.OVERLAY_API_TOKEN || mode === "none") return { url, protocols: undefined as string[] | undefined };

    if (mode.startsWith("query:")) {
        const key = mode.slice("query:".length) || "token";
        const u = new URL(url);
        u.searchParams.set(key, cfg.OVERLAY_API_TOKEN);
        return { url: u.toString(), protocols: undefined };
    }

    if (mode === "subprotocol:bearer") {
        // Non-standard but some WS servers accept token via subprotocol.
        return { url, protocols: ["bearer", cfg.OVERLAY_API_TOKEN] };
    }

    return { url, protocols: undefined };
}

function tryExtractPhoto(msg: any): Photo | null {
    const candidates: any[] = [msg];
    for (const k of ["data", "payload", "photo"]) {
        if (msg && typeof msg === "object" && msg[k] && typeof msg[k] === "object") candidates.push(msg[k]);
    }
    for (const obj of candidates) {
        if (!obj || typeof obj !== "object") continue;
        const url = obj.url || obj.photo_url || obj.image_url;
        if (!url || typeof url !== "string") continue;
        const id = Number(obj.id || 0);
        const name = String(obj.name || obj.title || "Photo");
        const added_by = Number(obj.added_by || obj.user_id || obj.addedBy || 0);
        const added_at = String(obj.added_at || obj.addedAt || "");
        return { id, name, url, added_by, added_at };
    }
    return null;
}

function wsConnect() {
    const baseWs = cfg.WS_URL || (originHttp ? wsFromHttp(originHttp) + "/api/ws/player" : "");
    if (!baseWs) return;

    const { url, protocols } = withWsToken(baseWs);

    let backoff = 800;
    const connect = () => {
        setStatus("ws: connecting");
        console.log("overlay: ws connecting to", url, { protocols });
        let ws: WebSocket;
        try {
            ws = protocols ? new WebSocket(url, protocols) : new WebSocket(url);
        } catch {
            setStatus("ws: failed");
            console.error("overlay: ws connection failed", url);
            window.setTimeout(connect, backoff);
            backoff = Math.min(backoff * 1.5, 8000);
            return;
        }

        ws.onopen = () => {
            backoff = 800;
            setStatus("ws: connected");
            console.log("overlay: ws open", { url, protocols });
        };

        ws.onmessage = async (ev) => {
            try {
                const raw = String(ev.data || "{}");
                console.debug("overlay: ws raw message", raw);
                const msg = JSON.parse(raw);
                console.debug("overlay: ws parsed message", msg);

                // photo event
                const p = tryExtractPhoto(msg);
                if (p && p.id > lastPhotoId) {
                    console.log("overlay: ws photo event", p);
                    lastPhotoId = p.id;
                    const by = await getUserName(String(p.added_by || ""));
                    showPhoto(resolveUrl(originHttp, p.url), `${p.name}${by ? ` | by ${by}` : ""}`);
                } else {
                    // non-photo messages (likely player state)
                    console.log("overlay: ws non-photo message", msg);
                    try {
                        if (msg && msg.type === "state") {
                            const state = msg as any;
                            const cur = state.current || null;
                            // update UI: render track info (prefer spotify oembed for cover)
                            if (cur && cur.spotify_id) {
                                try {
                                    // fetch oembed for better title/cover if possible
                                    const meta = await getSpotifyOEmbed(String(cur.spotify_id));
                                    const requester = await getUserName(String(cur.added_by || ""));
                                    renderTrack(meta, requester);
                                } catch (e) {
                                    // fallback to provided info
                                    renderTrack({ title: cur.name || "", artists: cur.artist || "", coverUrl: "" }, "");
                                }
                            }

                            // Playback control: prefer direct audio URL if provided
                            let audioUrl = cur && cur.url ? String(cur.url) : "";
                            // If url is a Spotify page, treat as spotify_id fallback
                            if (audioUrl.includes("open.spotify.com/track")) {
                                // extract spotify id from path
                                try {
                                    const u = new URL(audioUrl);
                                    const parts = u.pathname.split("/").filter(Boolean);
                                    const sid = parts.length ? parts[parts.length - 1] : "";
                                    if (sid) {
                                        cur.spotify_id = cur.spotify_id || sid;
                                        audioUrl = "";
                                    }
                                } catch {
                                    audioUrl = "";
                                }
                            }

                            if (audioUrl) {
                                if (state.playing) {
                                    try {
                                        await playAudioSrc(audioUrl);
                                        showPlayButton(false);
                                    } catch (e) {
                                        console.warn("overlay: autoplay blocked, showing play button", e);
                                        showPlayButton(true);
                                    }
                                } else {
                                    pauseAudio();
                                }
                                // hide spotify embed when using direct audio
                                showSpotifyEmbed(undefined, false);
                            } else if (cur && cur.spotify_id) {
                                // Prefer Spotify Web Playback SDK / Web API if we can obtain a user token
                                try {
                                    const ready = await initSpotifyPlayerIfNeeded();
                                    if (ready) {
                                        if (state.playing) {
                                            await spotifyPlayTrack(String(cur.spotify_id));
                                        } else {
                                            await spotifyPause();
                                        }
                                        // hide iframe fallback
                                        showSpotifyEmbed(undefined, false);
                                    } else {
                                        // fallback to Spotify embed; autoplay may be blocked by browser
                                        showSpotifyEmbed(String(cur.spotify_id), !!state.playing);
                                        if (!state.playing) pauseAudio();
                                    }
                                } catch (e) {
                                    console.warn(
                                        "overlay: spotify SDK/playback failed, falling back to embed",
                                        e
                                    );
                                    showSpotifyEmbed(String(cur.spotify_id), !!state.playing);
                                }
                            } else {
                                // nothing to play; ensure pause
                                pauseAudio();
                                showSpotifyEmbed(undefined, false);
                            }
                        }
                    } catch (e) {
                        console.error("overlay: error handling state message", e);
                    }
                }
            } catch {
                console.error("overlay: ws message handling error", ev.data);
            }
        };

        ws.onclose = () => {
            setStatus("ws: disconnected");
            console.warn("overlay: ws closed, reconnecting", url, { backoff });
            window.setTimeout(connect, backoff);
            backoff = Math.min(backoff * 1.5, 8000);
        };

        ws.onerror = () => {
            console.error("overlay: ws error");
            try { ws.close(); } catch { /* ignore */ }
        };
    };

    connect();
}

function main() {
    applyAnimation(coverImg);
    applyAnimation(photoImg);

    // Start loops
    void fetchSpotifyProfile();
    wsConnect();
    void pollQueueLoop();
    void pollPhotosLoop();
}

main();
// Removed trailing Markdown code fence
