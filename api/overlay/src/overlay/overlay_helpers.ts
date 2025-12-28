// overlay_helpers.ts: Кеши и вспомогательные функции для overlay
import { User, TrackMeta, Photo, QueueItem } from "./types";

export const userNameCache = new Map<string, string>();
export const trackCache = new Map<string, TrackMeta>();
const trackMetaPrefetchInFlight = new Set<string>();
const coverPrefetchCache = new Set<string>();

export async function fetchJson(url: string, headers: () => HeadersInit): Promise<any> {
    const r = await fetch(url, { headers: headers(), cache: "no-store" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
}

export async function getUserName(userId: string, apiUrl: (p: string) => string, headers: () => HeadersInit): Promise<string> {
    const key = userId.trim();
    if (!key) return "";
    const cached = userNameCache.get(key);
    if (cached) return cached;
    try {
        const data = (await fetchJson(apiUrl(`users/${encodeURIComponent(key)}`), headers)) as User;
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

function preloadCoverImage(url: string) {
    if (!url) return;
    if (coverPrefetchCache.has(url)) return;
    coverPrefetchCache.add(url);
    const img = new Image();
    img.src = url;
}

export async function getSpotifyOEmbed(trackId: string): Promise<TrackMeta> {
    const id = trackId.trim();
    const cached = trackCache.get(id);
    if (cached) return cached;
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
    let t = rawTitle;
    let a = "";
    const idx = rawTitle.lastIndexOf(" - ");
    if (idx > 0) {
        t = rawTitle.slice(0, idx).trim();
        a = rawTitle.slice(idx + 3).trim();
    }
    const meta = { title: t || id, artists: a, coverUrl: thumb };
    trackCache.set(id, meta);
    preloadCoverImage(thumb);
    return meta;
}

export function prefetchTrackMeta(trackIds: string[], offset = 0, limit = 0) {
    if (!Array.isArray(trackIds) || !trackIds.length) return;
    const normalized = trackIds
        .map((id) => (typeof id === "string" ? id.trim() : ""))
        .filter(Boolean);
    if (!normalized.length) return;
    const start = Math.max(0, offset);
    const end = limit > 0 ? Math.min(start + limit, normalized.length) : normalized.length;
    for (let i = start; i < end; i++) {
        const id = normalized[i];
        if (!id) continue;
        if (trackCache.has(id) || trackMetaPrefetchInFlight.has(id)) continue;
        trackMetaPrefetchInFlight.add(id);
        void getSpotifyOEmbed(id)
            .then((meta) => preloadCoverImage(meta.coverUrl))
            .catch(() => { /* tolerable failure */ })
            .finally(() => trackMetaPrefetchInFlight.delete(id));
    }
}
