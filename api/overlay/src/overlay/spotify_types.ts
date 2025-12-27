// Типы и переменные для Spotify SDK и очереди

export type PendingPlayback =
    | { kind: "none" }
    | { kind: "audio"; src: string }
    | { kind: "spotify"; spotifyId: string };

export let spotifyQueue: string[] = [];
export let spotifyQueueIndex: number = 0;
