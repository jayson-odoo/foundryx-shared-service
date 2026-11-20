/**
 * Owner's local check: after the BROWSER lost its network the live feed never
 * came back (the "Reconnecting" banner stayed until a reload; the legacy look,
 * which has no banner, simply stopped getting live updates). The retry read
 * the session first, the read failed while offline, and a missing token ended
 * the retry loop for good. Now it retries with a growing wait, drops the
 * socket when the browser goes offline, connects straight away when it comes
 * back online, and reports each change once.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { realConversationService as service, reconnectDelayMs } from './conversation-service.real';

const { getSession } = vi.hoisted(() => ({ getSession: vi.fn() }));
vi.mock('next-auth/react', () => ({ getSession }));
vi.mock('@/lib/embed-auth-store', () => ({ embedAuthStore: { getState: () => null } }));

class FakeSocket {
  static all: FakeSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: ((e: { code: number }) => void) | null = null;
  closed = false;
  constructor(public url: string) {
    FakeSocket.all.push(this);
  }
  open() {
    this.onopen?.();
  }
  drop(code = 1006) {
    this.closed = true;
    this.onclose?.({ code });
  }
  close() {
    if (this.closed) return;
    // A real socket reports its close later, asynchronously.
    this.closed = true;
    setTimeout(() => this.onclose?.({ code: 1000 }), 0);
  }
}

const realWebSocket = globalThis.WebSocket;
let online = true;

beforeEach(() => {
  vi.useFakeTimers();
  FakeSocket.all = [];
  globalThis.WebSocket = FakeSocket as unknown as typeof WebSocket;
  online = true;
  vi.spyOn(window.navigator, 'onLine', 'get').mockImplementation(() => online);
  getSession.mockReset();
  getSession.mockResolvedValue({ accessToken: 'jwt' });
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  globalThis.WebSocket = realWebSocket;
});

const last = () => FakeSocket.all[FakeSocket.all.length - 1];
const flush = async (ms = 0) => {
  await vi.advanceTimersByTimeAsync(ms);
};
const goOffline = () => {
  online = false;
  window.dispatchEvent(new Event('offline'));
};
const goOnline = () => {
  online = true;
  window.dispatchEvent(new Event('online'));
};

describe('live feed reconnect', () => {
  it('waits 1 s, then doubles, at most 30 s', () => {
    expect([0, 1, 2, 3, 4, 5, 6, 9].map(reconnectDelayMs)).toEqual([
      1000, 2000, 4000, 8000, 16000, 30000, 30000, 30000,
    ]);
  });

  it('comes back after the browser was offline, even when the session could not be read meanwhile', async () => {
    const changes: boolean[] = [];
    const stop = service.subscribe('ws-1', () => {}, (c) => changes.push(c));
    await flush();
    last().open();
    expect(changes).toEqual([true]);

    // The network goes: the socket drops; the session cannot be read.
    getSession.mockResolvedValue(null);
    goOffline();
    await flush();
    expect(changes).toEqual([true, false]);
    expect(last().closed).toBe(true);
    const before = FakeSocket.all.length;
    await flush(60_000);
    // Offline: no tries at all.
    expect(FakeSocket.all.length).toBe(before);

    // Back online, but the first session read still fails: it keeps trying.
    goOnline();
    await flush();
    expect(FakeSocket.all.length).toBe(before);
    getSession.mockResolvedValue({ accessToken: 'jwt' });
    await flush(reconnectDelayMs(0));
    expect(FakeSocket.all.length).toBe(before + 1);
    last().open();
    expect(changes).toEqual([true, false, true]);
    stop();
  });

  it('retries a dropped socket with a growing wait and starts over after it opens', async () => {
    const changes: boolean[] = [];
    const stop = service.subscribe('ws-1', () => {}, (c) => changes.push(c));
    await flush();
    last().drop();
    expect(changes).toEqual([false]);

    await flush(999);
    expect(FakeSocket.all.length).toBe(1);
    await flush(1);
    expect(FakeSocket.all.length).toBe(2);
    last().drop();
    await flush(1999);
    expect(FakeSocket.all.length).toBe(2);
    await flush(1);
    expect(FakeSocket.all.length).toBe(3);
    last().open();
    expect(changes).toEqual([false, true]);

    last().drop();
    await flush(1000);
    expect(FakeSocket.all.length).toBe(4);
    stop();
  });

  it('a session read that throws is retried, not the end of the feed', async () => {
    getSession.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    const stop = service.subscribe('ws-1', () => {});
    await flush();
    expect(FakeSocket.all.length).toBe(0);
    await flush(1000);
    expect(FakeSocket.all.length).toBe(1);
    stop();
  });

  it('a late close from a socket dropped while offline never flips a fresh connection back', async () => {
    const changes: boolean[] = [];
    const stop = service.subscribe('ws-1', () => {}, (c) => changes.push(c));
    await flush();
    const first = last();
    first.open();
    goOffline();
    goOnline();
    for (let i = 0; i < 5; i++) await Promise.resolve();
    const second = last();
    expect(second).not.toBe(first);
    second.open();
    await flush();
    expect(changes).toEqual([true, false, true]);
    stop();
  });

  it('stops for good once unsubscribed', async () => {
    const stop = service.subscribe('ws-1', () => {});
    await flush();
    stop();
    goOffline();
    goOnline();
    await flush(60_000);
    expect(FakeSocket.all.length).toBe(1);
  });
});
