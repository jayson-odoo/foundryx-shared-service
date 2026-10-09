import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { VisitorMessage, WebchatSessionResult } from '@/types/omnichannel';

const svc = {
  sendMessage: vi.fn(),
  listMessages: vi.fn(),
  subscribe: vi.fn(),
};
vi.mock('@/services/webchat-visitor-service', () => ({
  get webchatVisitorService() {
    return svc;
  },
}));

import { useVisitorChat } from './use-visitor-chat';

const SESSION_EMPTY: WebchatSessionResult = {
  token: 'tok-1',
  expiresAt: new Date(Date.now() + 1000 * 60 * 60 * 24 * 30).toISOString(),
  visitorId: 'visitor-1',
  workspaceId: 'ws-1',
  config: {
    appearance: { accentColor: '#FF5A00', position: 'right', headerTitle: 'Chat', agentDisplayName: 'Support' },
    greeting: 'Hi there!',
    offlineGreeting: 'We are away.',
    preChat: { askName: false, askEmail: false, askPhone: false },
    agentDisplayName: 'Support',
    tenantName: null,
    brandTokens: {},
  },
  online: true,
  messages: [],
};

function agentMessage(overrides: Partial<VisitorMessage> = {}): VisitorMessage {
  return {
    id: 'm-1',
    direction: 'out',
    text: 'Hello!',
    media: null,
    quickReplies: null,
    agentName: 'Support',
    createdAt: new Date().toISOString(),
    status: 'sent',
    ...overrides,
  };
}

/** The loader window: `window.parent` in a real embed. The hook must post
 *  `ready` to it and accept its `session` frame - and nothing else. */
const loaderWindow = { postMessage: vi.fn() } as unknown as Window;

function embed(): void {
  Object.defineProperty(window, 'parent', { value: loaderWindow, configurable: true });
}

/** What the loader does once it has minted the session (BL-SS-183). */
function handOverSession(session: WebchatSessionResult = SESSION_EMPTY): void {
  act(() => {
    window.dispatchEvent(
      new MessageEvent('message', {
        source: loaderWindow,
        data: { source: 'fx-webchat-loader', type: 'session', payload: session },
      }),
    );
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  embed();
  svc.subscribe.mockReturnValue(() => {});
  svc.listMessages.mockResolvedValue({ data: [], nextAfter: null });
});

afterEach(() => {
  Object.defineProperty(window, 'parent', { value: window, configurable: true });
});

describe('useVisitorChat (plan 34 / A7b S4, loader-minted session - BL-SS-183)', () => {
  it('waits for the loader and announces `ready` instead of starting a session itself', () => {
    const { result } = renderHook(() => useVisitorChat('wk_test'));
    expect(result.current.phase).toBe('waiting');
    expect(result.current.session).toBeNull();
    const posted = vi.mocked(loaderWindow.postMessage).mock.calls[0]?.[0] as {
      source: string;
      type: string;
    };
    expect(posted).toMatchObject({ source: 'fx-webchat-panel', type: 'ready' });
  });

  it('adopts the session the loader hands over and exposes the greeting-driving config', async () => {
    const { result } = renderHook(() => useVisitorChat('wk_test'));
    handOverSession();
    await waitFor(() => expect(result.current.phase).toBe('ready'));
    expect(result.current.session?.config.greeting).toBe('Hi there!');
    expect(result.current.messages).toEqual([]);
  });

  it('ignores a session frame from any window other than the embedding loader', async () => {
    const { result } = renderHook(() => useVisitorChat('wk_test'));
    act(() => {
      window.dispatchEvent(
        new MessageEvent('message', {
          source: { postMessage: vi.fn() } as unknown as Window,
          data: { source: 'fx-webchat-loader', type: 'session', payload: SESSION_EMPTY },
        }),
      );
    });
    expect(result.current.phase).toBe('waiting');
    expect(result.current.session).toBeNull();
  });

  it('ignores a malformed session payload rather than chatting with a bad token', () => {
    const { result } = renderHook(() => useVisitorChat('wk_test'));
    act(() => {
      window.dispatchEvent(
        new MessageEvent('message', {
          source: loaderWindow,
          data: { source: 'fx-webchat-loader', type: 'session', payload: { token: '' } },
        }),
      );
    });
    expect(result.current.phase).toBe('waiting');
  });

  it('needsPreChat is true only when a toggle is on AND there is no history yet', async () => {
    const { result } = renderHook(() => useVisitorChat('wk_test'));
    handOverSession({
      ...SESSION_EMPTY,
      config: { ...SESSION_EMPTY.config, preChat: { askName: true, askEmail: false, askPhone: false } },
    });
    await waitFor(() => expect(result.current.phase).toBe('ready'));
    expect(result.current.needsPreChat).toBe(true);
  });

  it('needsPreChat is false when every toggle is off', async () => {
    const { result } = renderHook(() => useVisitorChat('wk_test'));
    handOverSession();
    await waitFor(() => expect(result.current.phase).toBe('ready'));
    expect(result.current.needsPreChat).toBe(false);
  });

  it('needsPreChat is false when history already exists, even with toggles on', async () => {
    const { result } = renderHook(() => useVisitorChat('wk_test'));
    handOverSession({
      ...SESSION_EMPTY,
      config: { ...SESSION_EMPTY.config, preChat: { askName: true, askEmail: false, askPhone: false } },
      messages: [agentMessage()],
    });
    await waitFor(() => expect(result.current.phase).toBe('ready'));
    expect(result.current.needsPreChat).toBe(false);
  });

  it('send() appends the visitor message and opens the socket on the FIRST send', async () => {
    svc.sendMessage.mockResolvedValue({
      id: 'in-1',
      direction: 'in',
      text: 'Hello',
      media: null,
      quickReplies: null,
      agentName: null,
      createdAt: new Date().toISOString(),
      status: null,
    });
    const { result } = renderHook(() => useVisitorChat('wk_test'));
    handOverSession();
    await waitFor(() => expect(result.current.phase).toBe('ready'));
    expect(svc.subscribe).not.toHaveBeenCalled(); // AC-WEB-38's own S3 refusal - no contact yet

    await act(async () => {
      await result.current.send('Hello');
    });

    expect(result.current.messages).toHaveLength(1);
    expect(svc.subscribe).toHaveBeenCalledTimes(1);
    // The Bearer is the one the LOADER minted - never one this hook obtained.
    expect(svc.sendMessage).toHaveBeenCalledWith('wk_test', 'tok-1', expect.anything());
  });

  it('send() with a filled honeypot (server returns null) stores nothing client-side either', async () => {
    svc.sendMessage.mockResolvedValue(null);
    const { result } = renderHook(() => useVisitorChat('wk_test'));
    handOverSession();
    await waitFor(() => expect(result.current.phase).toBe('ready'));

    await act(async () => {
      await result.current.send('Hello');
    });

    expect(result.current.messages).toEqual([]);
  });

  it('a 429 send failure surfaces a rate-limit message, not a thrown error', async () => {
    const { ApiError } = await import('@/lib/api-client');
    svc.sendMessage.mockRejectedValue(new ApiError('Too many', 429));
    const { result } = renderHook(() => useVisitorChat('wk_test'));
    handOverSession();
    await waitFor(() => expect(result.current.phase).toBe('ready'));

    await act(async () => {
      await result.current.send('Hello');
    });

    expect(result.current.sendError).toMatch(/too many/i);
  });

  it("reuses an existing contact's socket immediately when history arrives with the session", async () => {
    renderHook(() => useVisitorChat('wk_test'));
    handOverSession({ ...SESSION_EMPTY, messages: [agentMessage()] });
    await waitFor(() => expect(svc.subscribe).toHaveBeenCalledTimes(1));
  });

  it('a re-minted session (the loader `identify()` path) replaces the transcript and the transport', async () => {
    const unsubscribe = vi.fn();
    svc.subscribe.mockReturnValue(unsubscribe);
    const { result } = renderHook(() => useVisitorChat('wk_test'));
    handOverSession({ ...SESSION_EMPTY, messages: [agentMessage({ id: 'anon-1', text: 'anon' })] });
    await waitFor(() => expect(svc.subscribe).toHaveBeenCalledTimes(1));

    handOverSession({
      ...SESSION_EMPTY,
      token: 'tok-2',
      visitorId: 'visitor-2',
      messages: [agentMessage({ id: 'known-1', text: 'known' })],
    });

    await waitFor(() => expect(result.current.session?.token).toBe('tok-2'));
    expect(unsubscribe).toHaveBeenCalled();
    expect(result.current.messages.map((m) => m.id)).toEqual(['known-1']);
  });
});
