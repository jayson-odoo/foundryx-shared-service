/**
 * Embed handshake tests (sprint-4/11 AC-11H-13/14): ready→init→session→paint,
 * origin rejection, theme apply, needToken refresh. Mocks window.parent
 * postMessage + `message` events + fetch (the `/embed/session` exchange).
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { embedAuthStore } from '@/lib/embed-auth-store';

import { PROTOCOL_VERSION, type EmbedEnvelope } from './embed-protocol';
import { useEmbedSession } from './use-embed-session';

const PARENT_ORIGIN = 'https://parent.example';

/** Base64url-encode a JSON object (no signature — the widget only decodes). */
function b64url(obj: unknown): string {
  return btoa(JSON.stringify(obj)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

/** A JWT whose payload carries `allowedOrigins` (+ scope/workspaceId). */
function makeAssertion(allowedOrigins: string[], scope = 'thread:cnt-001', workspaceId = 'wsp-1'): string {
  const header = b64url({ alg: 'HS256', typ: 'JWT' });
  const payload = b64url({ allowedOrigins, scope, workspaceId });
  return `${header}.${payload}.sig`;
}

const SESSION_RESPONSE = {
  accessToken: 'embed-access-token',
  expiresIn: 900,
  agent: { id: 'ext-agent-1', name: 'Aisha', avatarUrl: null },
  workspace: { id: 'wsp-1', name: 'General' },
  scope: 'thread:cnt-001',
  caps: ['reply', 'assign'],
};

function fetchOk() {
  return vi.fn().mockResolvedValue({ ok: true, json: async () => SESSION_RESPONSE });
}

function dispatch(type: string, payload: unknown, origin: string): void {
  const envelope: EmbedEnvelope<unknown> = { v: PROTOCOL_VERSION, type: type as never, payload };
  act(() => {
    window.dispatchEvent(new MessageEvent('message', { data: envelope, origin }));
  });
}

let postSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  postSpy = vi.spyOn(window.parent, 'postMessage').mockImplementation(() => {});
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  embedAuthStore.clear();
  document.documentElement.removeAttribute('style');
  document.documentElement.classList.remove('dark');
});

function postedTypes(): string[] {
  return postSpy.mock.calls.map((c) => (c[0] as EmbedEnvelope<unknown>).type);
}

describe('useEmbedSession handshake', () => {
  it('posts `ready` to window.parent on mount', () => {
    global.fetch = fetchOk();
    renderHook(() => useEmbedSession());
    expect(postedTypes()).toContain('ready');
    const ready = postSpy.mock.calls.find((c) => (c[0] as EmbedEnvelope<unknown>).type === 'ready')!;
    expect((ready[0] as EmbedEnvelope<unknown>).v).toBe(PROTOCOL_VERSION);
    expect(ready[1]).toBe('*'); // only the empty ready ping uses '*'
  });

  it('IGNORES `init` from a non-allowed origin (no session exchange)', async () => {
    const fetchMock = fetchOk();
    global.fetch = fetchMock;
    const { result } = renderHook(() => useEmbedSession());

    dispatch('init', { assertion: makeAssertion([PARENT_ORIGIN]) }, 'https://evil.example');

    await Promise.resolve();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.current.status).toBe('awaiting-init');
    expect(embedAuthStore.getState()).toBeNull();
  });

  it('exchanges the assertion on `init` from an allowed origin and paints', async () => {
    const fetchMock = fetchOk();
    global.fetch = fetchMock;
    const { result } = renderHook(() => useEmbedSession());

    dispatch('init', { assertion: makeAssertion([PARENT_ORIGIN]) }, PARENT_ORIGIN);

    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain('/embed/session');
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      assertion: makeAssertion([PARENT_ORIGIN]),
    });
    // Token held in memory for the reused conversation service.
    expect(embedAuthStore.getState()).toEqual({
      accessToken: 'embed-access-token',
      workspaceId: 'wsp-1',
      agentId: 'ext-agent-1',
    });
    expect(result.current.contactId).toBe('cnt-001');
    expect(result.current.session?.caps).toEqual(['reply', 'assign']);
  });

  it('applies theme CSS vars + colorScheme from `init`', async () => {
    global.fetch = fetchOk();
    const { result } = renderHook(() => useEmbedSession());

    dispatch(
      'init',
      {
        assertion: makeAssertion([PARENT_ORIGIN]),
        theme: { primary: '#123456', vars: { '--foundryx-info': '#0000ff' } },
        colorScheme: 'dark',
      },
      PARENT_ORIGIN,
    );

    await waitFor(() => expect(result.current.status).toBe('ready'));
    const root = document.documentElement;
    expect(root.style.getPropertyValue('--primary')).toBe('#123456');
    expect(root.style.getPropertyValue('--foundryx-primary')).toBe('#123456');
    expect(root.style.getPropertyValue('--foundryx-info')).toBe('#0000ff');
    expect(root.classList.contains('dark')).toBe(true);
  });

  it('applies a later live `theme` message', async () => {
    global.fetch = fetchOk();
    const { result } = renderHook(() => useEmbedSession());
    dispatch('init', { assertion: makeAssertion([PARENT_ORIGIN]) }, PARENT_ORIGIN);
    await waitFor(() => expect(result.current.status).toBe('ready'));

    dispatch('theme', { theme: { primary: '#abcdef' }, colorScheme: 'light' }, PARENT_ORIGIN);
    expect(document.documentElement.style.getPropertyValue('--primary')).toBe('#abcdef');
    expect(document.documentElement.classList.contains('dark')).toBe(false);
  });

  it('posts `needToken` before expiry and re-exchanges on `token`', async () => {
    vi.useFakeTimers();
    const fetchMock = fetchOk();
    global.fetch = fetchMock;
    const { result } = renderHook(() => useEmbedSession());

    const flush = () =>
      act(async () => {
        await Promise.resolve();
        await Promise.resolve();
        await Promise.resolve();
      });

    dispatch('init', { assertion: makeAssertion([PARENT_ORIGIN]) }, PARENT_ORIGIN);
    await flush(); // settle the exchange
    expect(result.current.status).toBe('ready');

    // Refresh fires at ~80% of the 900s lifetime.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(900 * 1000 * 0.8);
    });
    expect(postedTypes()).toContain('needToken');
    const needToken = postSpy.mock.calls.find(
      (c) => (c[0] as EmbedEnvelope<unknown>).type === 'needToken',
    )!;
    expect(needToken[1]).toBe(PARENT_ORIGIN); // origin-pinned, never '*'

    dispatch('token', { assertion: makeAssertion([PARENT_ORIGIN]) }, PARENT_ORIGIN);
    await flush();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('ignores a `token` message from a foreign origin', async () => {
    const fetchMock = fetchOk();
    global.fetch = fetchMock;
    const { result } = renderHook(() => useEmbedSession());
    dispatch('init', { assertion: makeAssertion([PARENT_ORIGIN]) }, PARENT_ORIGIN);
    await waitFor(() => expect(result.current.status).toBe('ready'));

    dispatch('token', { assertion: makeAssertion([PARENT_ORIGIN]) }, 'https://evil.example');
    await Promise.resolve();
    expect(fetchMock).toHaveBeenCalledTimes(1); // no re-exchange
  });
});
