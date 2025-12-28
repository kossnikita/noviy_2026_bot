// track_render.ts: функция для отрисовки информации о треке
import { TrackMeta } from "./types";
import { titleEl, artistsEl, albumEl, requestedByEl, coverImg } from "./dom";
import { applyAnimation, safeSetImage } from "./dom_helpers";

export function renderTrack(meta: TrackMeta, requestedBy: string) {
    console.log("overlay: renderTrack", { title: meta.title, artists: meta.artists, coverUrl: meta.coverUrl, requestedBy });
    titleEl.textContent = meta.title || "Ожидание";
    artistsEl.textContent = meta.artists || "";
    albumEl.textContent = "";
    requestedByEl.textContent = requestedBy ? `Заказано: ${requestedBy}` : "";
    safeSetImage(coverImg, meta.coverUrl);
    applyAnimation(coverImg);
}
