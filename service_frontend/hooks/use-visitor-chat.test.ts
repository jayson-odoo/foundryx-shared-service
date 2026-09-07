import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { VisitorMessage, WebchatSessionResult } from '@/types/omnichannel';

const svc = {
  startSession: vi.fn(),
  sendMessage: vi.fn(),
  listMessages: vi.fn(),
  subscribe: vi.fn(),
};
vi.mock('@/services/webchat-visitor-service', () => ({
  get webchatVisitorService() {
    return svc;
  },
}));

import { __resetWebchatVisitorStorageForTests } from '@/lib/webchat-visitor-storage';
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

beforeEach(() => {
  vi.clearAllMocks();
  __resetWebchatVisitorStorageForTests();
  window.localStorage.clear();
  svc.startSession.mockResolvedValue(SESSION_EMPTY);
  svc.subscribe.mockReturnValue(() => {});
});

describe('useVisitorChat (plan 34 / A7b S4)', () => {
  it('loads a fresh session and exposes the greeting-driving config', async () => {
    const { result } = renderHook(() => useVisitorChat('wk_test'));
    await waitFor(() => expect(result.current.phase).toBe('ready'));
    expect(result.current.session?.config.greeting).toBe('Hi there!');
    expect(result.current.messages).toEqual([]);
  });

  it('needsPreChat is true only when a toggle is on AND there is no history yet', async () => {
    svc.startSession.mockResolvedValue({
      ...SESSION_EMPTY,
      config: { ...SESSION_EMPTY.config, preChat: { askName: true, askEmail: false, askPhone: false } },
    });
    const { result } = renderHook(() => useVisitorChat('wk_test'));
    await waitFor(() => expect(result.current.phase).toBe('ready'));
    expect(result.current.needsPreChat).toBe(true);
  });

  it('needsPreChat is false when every toggle is off', async () => {
    const { result } = renderHook(() => useVisitorChat('wk_test'));
    await waitFor(() => expect(result.current.phase).toBe('ready'));
    expect(result.current.needsPreChat).toBe(false);
  });

  it('needsPreChat is false when history already exists, even with toggles on', async () => {
    svc.startSession.mockResolvedValue({
      ...SESSION_EMPTY,
      config: { ...SESSION_EMPTY.config, preChat: { askName: true, askEmail: false, askPhone: false } },
      messages: [agentMessage()],
    });
    const { result } = renderHook(() => useVisitorChat('wk_test'));
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
    await waitFor(() => expect(result.current.phase).toBe('ready'));
    expect(svc.subscribe).not.toHaveBeenCalled(); // AC-WEB-38's own S3 refusal - no contact yet

    await act(async () => {
      await result.current.send('Hello');
    });

    expect(result.current.messages).toHaveLength(1);
    expect(svc.subscribe).toHaveBeenCalledTimes(1);
  });

  it('send() with a filled honeypot (server returns null) stores nothing client-side either', async () => {
    svc.sendMessage.mockResolvedValue(null);
    const { result } = renderHook(() => useVisitorChat('wk_test'));
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
    await waitFor(() => expect(result.current.phase).toBe('ready'));

    await act(async () => {
      await result.current.send('Hello');
    });

    expect(result.current.sendError).toMatch(/too many/i);
  });

  it('reuses an existing contact\'s socket immediately when history already exists on load', async () => {
    svc.startSession.mockResolvedValue({ ...SESSION_EMPTY, messages: [agentMessage()] });
    renderHook(() => useVisitorChat('wk_test'));
    await waitFor(() => expect(svc.subscribe).toHaveBeenCalledTimes(1));
  });
});
