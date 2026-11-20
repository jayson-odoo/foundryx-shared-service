import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Channel } from '@/types/omnichannel';

const svc = { listByWorkspace: vi.fn() };
const listByWorkspace = svc.listByWorkspace;
vi.mock('@/services/channel-service', () => ({
  get channelService() {
    return svc;
  },
}));

import { useWorkspaceHasActiveChannel } from './use-workspace-has-active-channel';

const ch = (over: Partial<Channel>) => ({ id: 'c1', isActive: true, isTrashed: false, ...over }) as Channel;

describe('useWorkspaceHasActiveChannel', () => {
  beforeEach(() => {
    listByWorkspace.mockReset();
  });

  it('true when the workspace has an active, non-trashed channel', async () => {
    listByWorkspace.mockResolvedValue([ch({ isActive: false }), ch({ id: 'c2' })]);
    const { result } = renderHook(() => useWorkspaceHasActiveChannel('ws-1'));
    await waitFor(() => expect(result.current).toBe(true));
    expect(listByWorkspace).toHaveBeenCalledWith('ws-1');
  });

  it('false when every channel is inactive or trashed, or there are none', async () => {
    listByWorkspace.mockResolvedValue([ch({ isActive: false }), ch({ id: 'c2', isTrashed: true })]);
    const { result } = renderHook(() => useWorkspaceHasActiveChannel('ws-1'));
    await waitFor(() => expect(result.current).toBe(false));
  });

  it('null (unknown) when the list cannot be read, e.g. no channels.read', async () => {
    listByWorkspace.mockRejectedValue(new Error('403'));
    const { result } = renderHook(() => useWorkspaceHasActiveChannel('ws-1'));
    await waitFor(() => expect(listByWorkspace).toHaveBeenCalled());
    expect(result.current).toBeNull();
  });

  it('null without a workspace, and no call', () => {
    const { result } = renderHook(() => useWorkspaceHasActiveChannel(null));
    expect(result.current).toBeNull();
    expect(listByWorkspace).not.toHaveBeenCalled();
  });
});
