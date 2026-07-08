import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const svc = {
  list: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  remove: vi.fn(),
};
vi.mock('@/services/quick-reply-service', () => ({
  get quickReplyService() {
    return svc;
  },
}));

import { useQuickReplies } from './use-quick-replies';

const row = (id: string, shortcut: string | null, body: string) => ({
  id,
  workspaceId: 'wsp-1',
  shortcut,
  body,
});

beforeEach(() => {
  vi.clearAllMocks();
  svc.list.mockResolvedValue([row('qr-1', '/hi', 'Hi')]);
});

describe('useQuickReplies', () => {
  it('stays idle (no fetch) until a workspace id resolves', async () => {
    const { result } = renderHook(() => useQuickReplies(null));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(svc.list).not.toHaveBeenCalled();
    expect(result.current.items).toEqual([]);
  });

  it('loads rows for a workspace on mount', async () => {
    const { result } = renderHook(() => useQuickReplies('wsp-1'));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(svc.list).toHaveBeenCalledWith('wsp-1');
    expect(result.current.items.length).toBe(1);
    expect(result.current.error).toBeNull();
  });

  it('surfaces a load error', async () => {
    svc.list.mockRejectedValueOnce(new Error('boom'));
    const { result } = renderHook(() => useQuickReplies('wsp-1'));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBe('boom');
  });

  it('create calls the service then reloads', async () => {
    svc.create.mockResolvedValue(row('qr-2', '/new', 'New'));
    const { result } = renderHook(() => useQuickReplies('wsp-1'));
    await waitFor(() => expect(result.current.loading).toBe(false));
    svc.list.mockResolvedValue([row('qr-1', '/hi', 'Hi'), row('qr-2', '/new', 'New')]);
    await act(async () => {
      await result.current.create({ shortcut: '/new', body: 'New' });
    });
    expect(svc.create).toHaveBeenCalledWith('wsp-1', { shortcut: '/new', body: 'New' });
    await waitFor(() => expect(result.current.items.length).toBe(2));
  });

  it('remove calls the service then reloads', async () => {
    const { result } = renderHook(() => useQuickReplies('wsp-1'));
    await waitFor(() => expect(result.current.loading).toBe(false));
    svc.list.mockResolvedValue([]);
    await act(async () => {
      await result.current.remove('qr-1');
    });
    expect(svc.remove).toHaveBeenCalledWith('wsp-1', 'qr-1');
    await waitFor(() => expect(result.current.items.length).toBe(0));
  });
});
