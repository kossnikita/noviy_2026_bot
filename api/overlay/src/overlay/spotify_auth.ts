// Spotify authorization UI and polling logic
import { OverlayConfig } from "./types";
import { el } from "./dom";

let spotifyIframe: HTMLIFrameElement | null = null;
let spotifyAuthPollTimer: number | null = null;
let spotifyAuthPanelVisible = false;

export function ensureSpotifyIframe() {
    if (spotifyIframe) return spotifyIframe;
    try {
        spotifyIframe = document.createElement("iframe");
        spotifyIframe.id = "noviy-spotify-embed";
        spotifyIframe.classList.add("overlay-spotify-embed");
        spotifyIframe.setAttribute("allow", "autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture");
        const trackLayer = el<HTMLDivElement>("trackLayer");
        trackLayer.appendChild(spotifyIframe);
        return spotifyIframe;
    } catch (e) {
        console.warn("overlay: failed to create spotify iframe", e);
        spotifyIframe = null;
        return spotifyIframe;
    }
}

export function hideSpotifyEmbed() {
    if (!spotifyIframe) return;
    try {
        spotifyIframe.style.display = "none";
        spotifyIframe.src = "about:blank";
    } catch {}
}

const spotifyAuthPanel = (() => {
    try {
        const wrap = document.createElement("div");
        wrap.id = "noviy-spotify-auth";
        wrap.classList.add("overlay-spotify-auth");

        const msg = document.createElement("div");
        msg.id = "noviy-spotify-auth-msg";
        msg.textContent = "Spotify is not connected.";
        msg.classList.add("overlay-spotify-auth__message");
        wrap.appendChild(msg);

        const btn = document.createElement("button");
        btn.id = "noviy-spotify-auth-button";
        btn.textContent = "Authorize Spotify";
        btn.classList.add("overlay-spotify-auth__button");
        wrap.appendChild(btn);

        document.body.appendChild(wrap);
        return { wrap, msg, btn };
    } catch (e) {
        console.warn("overlay: failed to create spotify auth panel", e);
        return null as unknown as { wrap: HTMLDivElement; msg: HTMLDivElement; btn: HTMLButtonElement };
    }
})();

export function showSpotifyAuthPanel(visible: boolean, message?: string) {
    if (!spotifyAuthPanel) return;
    if (message) spotifyAuthPanel.msg.textContent = message;
    spotifyAuthPanel.wrap.style.display = visible ? "block" : "none";
    spotifyAuthPanelVisible = visible;
    if (!visible && spotifyAuthPollTimer) {
        window.clearInterval(spotifyAuthPollTimer);
        spotifyAuthPollTimer = null;
    }
    if (!visible) hideSpotifyEmbed();
}

export function allowSpotifyEmbedWidgetNow(): boolean {
    return spotifyAuthPanelVisible;
}

export function spotifyLoginUrl(cfg: OverlayConfig, apiUrl: (p: string) => string): string | null {
    const t = (cfg.OVERLAY_API_TOKEN || "").trim();
    if (!t) return null;
    const u = new URL(apiUrl("spotify/login"), window.location.origin);
    u.searchParams.set("token", t);
    return u.toString();
}

export function spotifyAuthPollUntilConnected(fetchSpotifyAccessTokenFromBackend: (opts?: { force?: boolean }) => Promise<string | null>, showSpotifyAuthPanel: (visible: boolean, message?: string) => void, setStatus: (msg: string) => void) {
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

export function setupSpotifyAuthButton(cfg: OverlayConfig, apiUrl: (p: string) => string, fetchSpotifyAccessTokenFromBackend: (opts?: { force?: boolean }) => Promise<string | null>, showSpotifyAuthPanel: (visible: boolean, message?: string) => void, setStatus: (msg: string) => void) {
    if (spotifyAuthPanel) {
        spotifyAuthPanel.btn.addEventListener("click", () => {
            const u = spotifyLoginUrl(cfg, apiUrl);
            if (!u) {
                showSpotifyAuthPanel(true, "Missing OVERLAY_API_TOKEN. Set it in overlay config.");
                return;
            }
            try {
                window.open(u, "_blank", "noopener,noreferrer");
            } catch {
                window.location.href = u;
                return;
            }
            showSpotifyAuthPanel(true, "Complete Spotify login in the opened tab, then return here.");
            spotifyAuthPollUntilConnected(fetchSpotifyAccessTokenFromBackend, showSpotifyAuthPanel, setStatus);
        });
    }
}
