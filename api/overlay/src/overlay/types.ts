// Общие типы для overlay

export type OverlayConfig = {
    OVERLAY_API_TOKEN: string;
    WS_URL: string;
    PHOTO_POLL_INTERVAL_MS: number;
    PHOTO_DISPLAY_MS: number;
    QUEUE_POLL_INTERVAL_MS: number;
    SPOTIFY_OAUTH_TOKEN?: string;
    WS_TOKEN_MODE: string;
};

export type QueueItem = import("../utils").QueueItem;

export type Photo = {
    id: number;
    name: string;
    url: string;
    added_by: number;
    added_at: string;
};

export type User = {
    id?: string | number;
    username?: string;
    first_name?: string;
    last_name?: string;
    display_name?: string;
    name?: string;
};

export type TrackMeta = {
    title: string;
    artists: string;
    coverUrl: string;
};
