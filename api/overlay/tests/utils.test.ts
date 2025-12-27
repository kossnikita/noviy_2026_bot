import {
  clampNum,
  cleanBaseUrl,
  isAbsoluteHttpUrl,
  pickRequesterId,
  pickTrackId,
  resolveUrl,
  wsFromHttp,
} from '../src/utils';

describe('overlay utils', () => {
  test('cleanBaseUrl trims and removes trailing slash', () => {
    expect(cleanBaseUrl(' /api/ ')).toBe('/api');
    expect(cleanBaseUrl('http://x/y/')).toBe('http://x/y');
    expect(cleanBaseUrl('')).toBe('');
  });

  test('isAbsoluteHttpUrl detects http/https (case-insensitive)', () => {
    expect(isAbsoluteHttpUrl('http://example.com')).toBe(true);
    expect(isAbsoluteHttpUrl('HTTPS://example.com')).toBe(true);
    expect(isAbsoluteHttpUrl('/api')).toBe(false);
  });

  test('wsFromHttp converts http(s) to ws(s)', () => {
    expect(wsFromHttp('http://example.com/api')).toBe('ws://example.com/api');
    expect(wsFromHttp('https://example.com/api')).toBe('wss://example.com/api');
    expect(wsFromHttp('/api')).toBe('/api');
  });

  test('clampNum clamps to bounds', () => {
    expect(clampNum(5, 0, 10)).toBe(5);
    expect(clampNum(-1, 0, 10)).toBe(0);
    expect(clampNum(999, 0, 10)).toBe(10);
  });

  test('pickTrackId picks first available id', () => {
    expect(pickTrackId({ spotify_id: 's1', track_id: 't1', trackId: 't2' })).toBe('s1');
    expect(pickTrackId({ track_id: 't1', trackId: 't2' })).toBe('t1');
    expect(pickTrackId({ trackId: 't2' })).toBe('t2');
    expect(pickTrackId({})).toBe('');
  });

  test('pickRequesterId prefers requester fields over added_by', () => {
    expect(pickRequesterId({ requester_id: 'r1', added_by: 42 })).toBe('r1');
    expect(pickRequesterId({ requesterId: 'r2', added_by: 42 })).toBe('r2');
    expect(pickRequesterId({ person_id: 'p3', added_by: 42 })).toBe('p3');
    expect(pickRequesterId({ added_by: 42 })).toBe('42');
    expect(pickRequesterId({})).toBe('');
  });

  test('resolveUrl resolves absolute and relative paths', () => {
    // jsdom default origin is http://localhost
    expect(resolveUrl('http://example.com/api', '/photos/1')).toBe('http://example.com/photos/1');
    expect(resolveUrl('http://example.com/api', 'users/1')).toBe('http://example.com/api/users/1');

    expect(resolveUrl('/api', '/health')).toBe(`${window.location.origin}/health`);
  });
});
