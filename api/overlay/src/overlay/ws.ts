// ws.ts: WebSocket logic for overlay
import { OverlayConfig, Photo, TrackMeta, QueueItem } from "./types";
import { wsFromHttp } from "../utils";
import { resolveUrl } from "./utils";
import { getUserName, getSpotifyOEmbed } from "./overlay_helpers";
import { applyAnimation, safeSetImage } from "./dom_helpers";
import { photoImg, photoCaption, photoLayer, coverImg, titleEl, artistsEl, albumEl, requestedByEl } from "./dom";

export function withWsToken(url: string, cfg: OverlayConfig): { url: string; protocols: string[] | undefined } {
    const mode = (cfg.WS_TOKEN_MODE || "none").trim();
    if (!cfg.OVERLAY_API_TOKEN || mode === "none") return { url, protocols: undefined };
    if (mode.startsWith("query:")) {
        const key = mode.slice("query:".length) || "token";
        const u = new URL(url);
        u.searchParams.set(key, cfg.OVERLAY_API_TOKEN);
        return { url: u.toString(), protocols: undefined };
    }
    if (mode === "subprotocol:bearer") {
        return { url, protocols: ["bearer", cfg.OVERLAY_API_TOKEN] };
    }
    return { url, protocols: undefined };
}

export function tryExtractPhoto(msg: any): Photo | null {
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

// wsConnect will be refactored to accept callbacks for photo and state events
export function wsConnect(cfg: OverlayConfig, originHttp: string, apiUrl: (p: string) => string, setStatus: (msg: string) => void, onPhoto: (photo: Photo) => void, onState: (msg: any) => void) {
    const baseWs = cfg.WS_URL || (originHttp ? wsFromHttp(originHttp) + "/api/ws/player" : "");
    if (!baseWs) return;
    const { url, protocols } = withWsToken(baseWs, cfg);
    let backoff = 800;
    const connect = () => {
        setStatus("ws: connecting");
        let ws: WebSocket;
        try {
            ws = protocols ? new WebSocket(url, protocols) : new WebSocket(url);
        } catch {
            setStatus("ws: failed");
            window.setTimeout(connect, backoff);
            backoff = Math.min(backoff * 1.5, 8000);
            return;
        }
        ws.onopen = () => {
            backoff = 800;
            setStatus("ws: connected");
        };
        ws.onmessage = async (ev) => {
            try {
                const raw = String(ev.data || "{}");
                const msg = JSON.parse(raw);
                // photo event
                const p = tryExtractPhoto(msg);
                if (p && p.id) {
                    onPhoto(p);
                } else {
                    onState(msg);
                }
            } catch {
                // ignore
            }
        };
        ws.onclose = () => {
            setStatus("ws: disconnected");
            window.setTimeout(connect, backoff);
            backoff = Math.min(backoff * 1.5, 8000);
        };
        ws.onerror = () => {
            try { ws.close(); } catch { /* ignore */ }
        };
    };
    connect();
}
