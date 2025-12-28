// spotify_sdk.ts: интеграция с Spotify Web Playback SDK и Web API
import { OverlayConfig } from "./types";

let spotifyPlayer: any = null;
let spotifyDeviceId: string | null = null;
let spotifySdkLoaded = false;
let spotifySdkPromise: Promise<void> | null = null;
let spotifyAccessToken: string | null = null;
let spotifyAccessTokenExpiresAt: number = 0;
let spotifyTokenLastAttemptAt = 0;
let spotifyPlaybackDisabledReason: string | null = null;
let spotifyStateListener: ((state: any) => void) | null = null;

export function setSpotifyStateListener(listener: ((state: any) => void) | null) {
    spotifyStateListener = listener;
}

export function getSpotifyDeviceId(): string | null {
    return spotifyDeviceId;
}

export function activateSpotifyElement(): boolean {
    if (!spotifyPlayer) {
        console.warn("spotify_sdk: cannot activate element - player not initialized");
        return false;
    }
    try {
        if (typeof spotifyPlayer.activateElement === "function") {
            spotifyPlayer.activateElement();
            console.log("spotify_sdk: activated element for autoplay");
            return true;
        } else {
            console.warn("spotify_sdk: activateElement not available");
            return false;
        }
    } catch (err) {
        console.warn("spotify_sdk: activateElement failed", err);
        return false;
    }
}

export function loadSpotifySdk(): Promise<void> {
    if (spotifySdkLoaded || (window as any).Spotify) {
        spotifySdkLoaded = true;
        return Promise.resolve();
    }
    if (spotifySdkPromise) return spotifySdkPromise;
    spotifySdkPromise = new Promise((resolve, reject) => {
        let done = false;
        const finish = (ok: boolean, err?: any) => {
            if (done) return;
            done = true;
            if (ok) {
                spotifySdkLoaded = true;
                resolve();
            } else {
                reject(err || new Error("Spotify SDK failed to load"));
            }
        };
        window.onSpotifyWebPlaybackSDKReady = () => {
            if ((window as any).Spotify) finish(true);
            else finish(false, new Error("Spotify SDK ready callback fired but window.Spotify is missing"));
        };
        const existing = document.querySelector('script[src="https://sdk.scdn.co/spotify-player.js"]') as HTMLScriptElement | null;
        if (existing) {
            const t = window.setTimeout(() => {
                if ((window as any).Spotify) finish(true);
                else finish(false, new Error("Spotify SDK load timeout"));
            }, 10000);
            existing.addEventListener("error", (e) => {
                window.clearTimeout(t);
                finish(false, e);
            });
            return;
        }
        const s = document.createElement("script");
        s.src = "https://sdk.scdn.co/spotify-player.js";
        s.async = true;
        const t = window.setTimeout(() => {
            if ((window as any).Spotify) finish(true);
            else finish(false, new Error("Spotify SDK load timeout"));
        }, 10000);
        s.onerror = (e) => {
            window.clearTimeout(t);
            finish(false, e);
        };
        document.head.appendChild(s);
    }).finally(() => {
        if (!spotifySdkLoaded) spotifySdkPromise = null;
    });
    return spotifySdkPromise;
}

export async function initSpotifyPlayerIfNeeded(cfg: OverlayConfig, getSpotifyAccessToken: () => Promise<string | null>, setStatus: (msg: string) => void): Promise<boolean> {
    if (spotifyPlaybackDisabledReason) {
        console.warn("overlay: spotify playback disabled", spotifyPlaybackDisabledReason);
        return false;
    }
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
            let done = false;
            const timeout = window.setTimeout(() => {
                if (done) return;
                done = true;
                console.warn("overlay: spotify player init timeout");
                setStatus("spotify: init timeout");
                resolve(false);
            }, 12000);
            const finish = (ok: boolean, reason?: string) => {
                if (done) return;
                done = true;
                window.clearTimeout(timeout);
                if (!ok && reason) spotifyPlaybackDisabledReason = reason;
                resolve(ok);
            };
            spotifyPlayer = new (window as any).Spotify.Player({
                name: "Noviy Overlay",
                getOAuthToken: (cb: (t: string) => void) => {
                    void getSpotifyAccessToken()
                        .then((t) => cb(t || ""))
                        .catch(() => cb(""));
                },
                volume: 0.8,
            });
            spotifyPlayer.addListener("player_state_changed", (state: any) => {
                try {
                    if (spotifyStateListener) spotifyStateListener(state);
                } catch (err) {
                    console.warn("overlay: spotify state listener failed", err);
                }
            });
            spotifyPlayer.addListener("ready", ({ device_id }: any) => {
                spotifyDeviceId = device_id;
                setStatus("spotify: ready");
                try {
                    if (typeof spotifyPlayer.activateElement === 'function') {
                        spotifyPlayer.activateElement();
                        console.log('spotify_sdk: activated element on ready event');
                    }
                } catch (err) {
                    console.warn('spotify_sdk: activateElement on ready failed', err);
                }                finish(true);
            });
            spotifyPlayer.addListener("not_ready", ({ device_id }: any) => {
                setStatus("spotify: not ready");
            });
            spotifyPlayer.addListener("initialization_error", (e: any) => {
                setStatus("spotify: init error");
                finish(false, "initialization_error");
            });
            spotifyPlayer.addListener("authentication_error", (e: any) => {
                setStatus("spotify: auth error");
                finish(false, "authentication_error");
            });
            spotifyPlayer.addListener("account_error", (e: any) => {
                setStatus("spotify: account error");
                finish(false, "account_error");
            });
            spotifyPlayer.connect().then((connected: boolean) => {
                if (!connected) setStatus("spotify: connect failed");
            });
        } catch (e) {
            resolve(false);
        }
    });
}

export async function spotifyApiRequest(path: string, method: string, body: any, getSpotifyAccessToken: () => Promise<string | null>) {
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

export async function enqueueSpotifyTrack(spotifyId: string, getSpotifyAccessToken: () => Promise<string | null>) {
    if (!spotifyDeviceId) throw new Error("No spotify device id");
    const uri = `spotify:track:${spotifyId}`;
    const path = `/me/player/queue?uri=${encodeURIComponent(uri)}&device_id=${encodeURIComponent(spotifyDeviceId)}`;
    await spotifyApiRequest(path, "POST", undefined, getSpotifyAccessToken);
}

export async function fetchSpotifyAccessTokenFromBackend(cfg: OverlayConfig, apiUrl: (p: string) => string, _overlayAuthHeader: () => string | null, showSpotifyAuthPanel: (visible: boolean, message?: string) => void, hideSpotifyEmbed: () => void, setStatus: (msg: string) => void, opts?: { force?: boolean }): Promise<string | null> {
    const now = Date.now();
    if (!opts?.force && now - spotifyTokenLastAttemptAt < 60_000) return spotifyAccessToken;
    spotifyTokenLastAttemptAt = now;
    const auth = _overlayAuthHeader();
    if (!auth) return null;
    try {
        const r = await fetch(apiUrl("spotify/token"), {
            method: "GET",
            headers: { Authorization: auth },
            cache: "no-store",
        });
        if (!r.ok) {
            const text = await r.text();
            if (r.status === 409) {
                let detail = "Spotify is not connected. Open /spotify/login to authorize.";
                try {
                    const j = JSON.parse(text);
                    if (j && typeof j.detail === "string") detail = j.detail;
                } catch { }
                showSpotifyAuthPanel(true, detail);
            } else if (r.status === 401 || r.status === 403) {
                showSpotifyAuthPanel(true, "Spotify auth requires a valid OVERLAY_API_TOKEN.");
            }
            return null;
        }
        const data = (await r.json()) as any;
        const token = String(data?.access_token || "").trim();
        const exp = Number(data?.expires_at || 0);
        if (!token) return null;
        spotifyAccessToken = token;
        spotifyAccessTokenExpiresAt = exp ? exp * 1000 : 0;
        showSpotifyAuthPanel(false);
        hideSpotifyEmbed();
        return token;
    } catch {
        return null;
    }
}

export async function getSpotifyAccessToken(cfg: OverlayConfig, fetchSpotifyAccessTokenFromBackend: (opts?: { force?: boolean }) => Promise<string | null>): Promise<string | null> {
    if (cfg.SPOTIFY_OAUTH_TOKEN) return cfg.SPOTIFY_OAUTH_TOKEN;
    const now = Date.now();
    if (spotifyAccessToken && spotifyAccessTokenExpiresAt) {
        if (now < spotifyAccessTokenExpiresAt - 30_000) return spotifyAccessToken;
    }
    return await fetchSpotifyAccessTokenFromBackend();
}

export async function fetchSpotifyProfile(getSpotifyAccessToken: () => Promise<string | null>, setStatus: (msg: string) => void) {
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
        if (!r.ok) return;
        const data = await r.json();
        const product = (data && data.product) ? String(data.product) : "unknown";
        setStatus(`spotify: ${product}`);
    } catch { }
}

export async function spotifyPlayTrack(spotifyId: string, getSpotifyAccessToken: () => Promise<string | null>, setStatus: (msg: string) => void) {
    if (!spotifyDeviceId) {
        await initSpotifyPlayerIfNeeded;
        if (!spotifyDeviceId) throw new Error("No spotify device id");
    }
    console.log("spotify_sdk: transferring playback to device", { deviceId: spotifyDeviceId, spotifyId });
    try {
        await spotifyApiRequest("/me/player", "PUT", { device_ids: [spotifyDeviceId], play: false }, getSpotifyAccessToken);
        console.log("spotify_sdk: device transfer complete");
    } catch (err) {
        console.warn("spotify_sdk: device transfer failed, continuing", err);
    }
    const uri = `spotify:track:${spotifyId}`;
    console.log("spotify_sdk: starting playback", { uri });
    await spotifyApiRequest(`/me/player/play?device_id=${encodeURIComponent(spotifyDeviceId!)}`, "PUT", { uris: [uri] }, getSpotifyAccessToken);
    console.log("spotify_sdk: playback started");
}

export async function spotifyPause(getSpotifyAccessToken: () => Promise<string | null>) {
    if (!spotifyDeviceId) return;
    await spotifyApiRequest(`/me/player/pause?device_id=${encodeURIComponent(spotifyDeviceId)}`, "PUT", undefined, getSpotifyAccessToken);
}

export async function spotifyNext(getSpotifyAccessToken: () => Promise<string | null>) {
    if (!spotifyDeviceId) return;
    await spotifyApiRequest(`/me/player/next?device_id=${encodeURIComponent(spotifyDeviceId)}`, "POST", undefined, getSpotifyAccessToken);
}

export async function spotifyPrev(getSpotifyAccessToken: () => Promise<string | null>) {
    if (!spotifyDeviceId) return;
    await spotifyApiRequest(`/me/player/previous?device_id=${encodeURIComponent(spotifyDeviceId)}`, "POST", undefined, getSpotifyAccessToken);
}

export async function getSpotifyCurrentTrackId(getSpotifyAccessToken: () => Promise<string | null>): Promise<string | null> {
    if (!spotifyDeviceId) return null;
    const token = await getSpotifyAccessToken();
    if (!token) return null;
    const url = `https://api.spotify.com/v1/me/player/currently-playing?device_id=${encodeURIComponent(spotifyDeviceId)}`;
    try {
        const res = await fetch(url, {
            method: "GET",
            headers: {
                Authorization: `Bearer ${token}`,
            },
            cache: "no-store",
        });
        if (res.status === 204) return null;
        if (!res.ok) {
            console.warn("overlay: failed to read spotify current track", res.status);
            return null;
        }
        const data = (await res.json()) as any;
        const id = data?.item?.id;
        if (typeof id === "string" && id.trim()) return id.trim();
        return null;
    } catch (err) {
        console.warn("overlay: spotify current track request failed", err);
        return null;
    }
}
