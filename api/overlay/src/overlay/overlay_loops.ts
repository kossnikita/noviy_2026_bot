// overlay_loops.ts: циклы опроса очереди и фотографий
import { QueueItem, Photo, OverlayConfig } from "./types";
import { clampNum, pickRequesterId, pickTrackId, resolveUrl } from "../utils";
import { fetchJson, getUserName, getSpotifyOEmbed } from "./overlay_helpers";
import { renderTrack } from "./track_render";
import { showPhoto } from "./photo_helpers";

export async function pollQueueLoop(cfg: OverlayConfig, apiUrl: (p: string) => string, headers: () => HeadersInit, setStatus: (msg: string) => void) {
    let lastTrackId = "";
    let lastRequester = "";
    const interval = () => clampNum(cfg.QUEUE_POLL_INTERVAL_MS, 500, 30000);
    while (true) {
        try {
            const data = await fetchJson(apiUrl("spotify-tracks?limit=200&offset=0"), headers);
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
                        getUserName(requesterId, apiUrl, headers),
                    ]);
                    renderTrack(meta, reqName);
                }
            }
            setStatus("ok");
        } catch (e) {
            setStatus("queue: error");
        }
        await new Promise((r) => setTimeout(r, interval()));
    }
}

export async function pollPhotosLoop(cfg: OverlayConfig, apiUrl: (p: string) => string, headers: () => HeadersInit, originHttp: string, setStatus: (msg: string) => void) {
    let lastPhotoId = 0;
    const interval = () => clampNum(cfg.PHOTO_POLL_INTERVAL_MS, 500, 30000);
    const displayMs = () => clampNum(cfg.PHOTO_DISPLAY_MS, 0, 600000);
    try {
        const init = await fetchJson(apiUrl("photos?limit=100&offset=0"), headers);
        if (Array.isArray(init)) {
            for (const p of init as Photo[]) {
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
            const data = await fetchJson(url, headers);
            const arr = Array.isArray(data) ? (data as Photo[]) : [];
            if (arr.length) {
                arr.sort((a, b) => (a.id || 0) - (b.id || 0));
                for (const p of arr) {
                    if ((p.id || 0) <= lastPhotoId) continue;
                    lastPhotoId = p.id;
                    const by = await getUserName(String(p.added_by || ""), apiUrl, headers);
                    const caption = `${p.name || "Photo"}${by ? ` | by ${by}` : ""}`;
                    showPhoto(resolveUrl(originHttp, p.url), caption);
                    await new Promise((r) => setTimeout(r, displayMs() + 150));
                }
            }
        } catch {
            // ignore
        }
        await new Promise((r) => setTimeout(r, interval()));
    }
}
