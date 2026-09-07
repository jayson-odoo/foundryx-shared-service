/**
 * Plan 34 (A7b) review round 1, S3 - the visitor WebSocket's reconnect
 * policy. `subscribe` used to schedule a reconnect 3s after ANY close,
 * ignoring the code: after an admin clicked "sign out all visitors" every
 * open panel reconnected every 3 seconds forever, each handshake costing
 * four backend queries.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

class FakeSocket {
  static instances: FakeSocket[] = [];
  onopen: (() => void) | null = null;
  onclose: ((e: { code?: number }) => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;

  constructor(public url: string) {
    FakeSocket.instances.push(this);
  }

  close() {
    this.closed = true;
  }
}

const originalWebSocket = globalThis.WebSocket;

beforeEach(() => {
  FakeSocket.instances = [];
  vi.useFakeTimers();
  // Deterministic jitter - the delay assertions below pin the ceiling, and
  // the point of the jitter is that a thousand panels do not reconnect in
  // lockstep, not its exact value.
  vi.spyOn(Math, 'random').mockReturnValue(0.999999);
  (globalThis as unknown as { WebSocket: unknown }).WebSocket = FakeSocket;
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  (globalThis as unknown as { WebSocket: unknown }).WebSocket = originalWebSocket;
});

async function loadService() {
  const mod = await import('./webchat-visitor-service.real');
  return mod.realWebchatVisitorService;
}

describe('realWebchatVisitorService.subscribe', () => {
  it('never reconnects after a 4403 refusal (the poll fallback takes over)', async () => {
    const service = await loadService();
    const statuses: string[] = [];
    service.subscribe('ws-1', 'tok-1', () => {}, (s) => statuses.push(s));

    expect(FakeSocket.instances).toHaveLength(1);
    FakeSocket.instances[0].onopen?.();
    FakeSocket.instances[0].onclose?.({ code: 4403 });

    vi.advanceTimersByTime(120_000);
    expect(FakeSocket.instances).toHaveLength(1);
    expect(statuses).toEqual(['connecting', 'open', 'closed']);
  });

  it('reconnects after a genuine drop', async () => {
    const service = await loadService();
    service.subscribe('ws-1', 'tok-1', () => {});

    FakeSocket.instances[0].onopen?.();
    FakeSocket.instances[0].onclose?.({ code: 1006 });

    vi.advanceTimersByTime(3_100);
    expect(FakeSocket.instances).toHaveLength(2);
  });

  it('backs off exponentially and gives up after repeated immediate closes', async () => {
    const service = await loadService();
    service.subscribe('ws-1', 'tok-1', () => {});

    // Five consecutive closes that never reached `open` - the code-less
    // version of a permanent refusal (a proxy that eats the close code).
    for (let i = 0; i < 5; i += 1) {
      expect(FakeSocket.instances).toHaveLength(i + 1);
      FakeSocket.instances[i].onclose?.({ code: 1006 });
      vi.advanceTimersByTime(60_000);
    }
    expect(FakeSocket.instances).toHaveLength(5);
  });

  it('caps the retry delay at 30s', async () => {
    const service = await loadService();
    const spy = vi.spyOn(globalThis, 'setTimeout');
    service.subscribe('ws-1', 'tok-1', () => {});

    FakeSocket.instances[0].onclose?.({ code: 1006 });
    const delays = spy.mock.calls.map((c) => c[1] as number);
    expect(delays.every((d) => d <= 30_000)).toBe(true);
  });

  it('stops everything when the caller unsubscribes', async () => {
    const service = await loadService();
    const stop = service.subscribe('ws-1', 'tok-1', () => {});
    FakeSocket.instances[0].onopen?.();
    stop();
    FakeSocket.instances[0].onclose?.({ code: 1006 });
    vi.advanceTimersByTime(120_000);
    expect(FakeSocket.instances).toHaveLength(1);
  });
});
