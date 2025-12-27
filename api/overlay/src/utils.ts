export function nowMs() {
  return Date.now();
}

export function clampNum(n: number, min: number, max: number) {
  return Math.max(min, Math.min(max, n));
}

export function cleanBaseUrl(url: string) {
  return (url || '').trim().replace(/\/$/, '');
}

export function isAbsoluteHttpUrl(url: string) {
  const u = (url || '').trim().toLowerCase();
  return u.startsWith('http://') || u.startsWith('https://');
}

export function toAbsoluteBaseUrl(baseUrl: string) {
  const b = cleanBaseUrl(baseUrl);
  if (!b) return '';
  if (isAbsoluteHttpUrl(b)) return b;
  if (b.startsWith('/')) {
    try {
      return new URL(b, window.location.origin).toString().replace(/\/$/, '');
    } catch {
      return b;
    }
  }
  return b;
}

export function wsFromHttp(baseUrl: string) {
  const u = cleanBaseUrl(baseUrl);
  if (u.startsWith('https://')) return 'wss://' + u.slice('https://'.length);
  if (u.startsWith('http://')) return 'ws://' + u.slice('http://'.length);
  return u;
}

export function resolveUrl(baseUrl: string, url: string) {
  const raw = (url || '').trim();
  if (!raw) return raw;
  if (/^https?:\/\//i.test(raw)) return raw;

  const absBase = toAbsoluteBaseUrl(baseUrl);

  try {
    if (raw.startsWith('/')) {
      if (absBase && isAbsoluteHttpUrl(absBase)) {
        const b = new URL(absBase);
        return new URL(raw, `${b.protocol}//${b.host}`).toString();
      }
      return new URL(raw, window.location.origin).toString();
    }
    if (absBase && isAbsoluteHttpUrl(absBase)) {
      return new URL(raw, absBase.endsWith('/') ? absBase : absBase + '/').toString();
    }
    return new URL(
      raw,
      window.location.origin.endsWith('/') ? window.location.origin : window.location.origin + '/',
    ).toString();
  } catch {
    return raw;
  }
}

export type QueueItem = {
  spotify_id?: string;
  track_id?: string;
  trackId?: string;
  added_by?: number;
  requester_id?: string;
  requesterId?: string;
  person_id?: string;
};

export function pickTrackId(item: QueueItem): string {
  return (item.spotify_id || item.track_id || item.trackId || '').toString();
}

export function pickRequesterId(item: QueueItem): string {
  const fromOld = item.requester_id || item.requesterId || item.person_id;
  if (fromOld) return fromOld.toString();
  if (typeof item.added_by === 'number') return String(item.added_by);
  return '';
}
