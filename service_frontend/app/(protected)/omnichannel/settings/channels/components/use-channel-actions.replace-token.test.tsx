/**
 * Plan 42 (AC-42-20, AC-42-25): the `replace-token` action in the channel
 * action registry, and the service method it reaches through the hook.
 * The shell hides an action whose `permission` the user lacks, so the
 * permission key is the assertion for "not without the permission".
 */
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { Channel } from '@/types/omnichannel';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock('@/lib/toast', () => ({ toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() } }));

const wa = { id: 'c1', channelType: 'WHATSAPP', isTrashed: false, status: 'ERROR' } as Channel;
const web = { id: 'c2', channelType: 'WEBCHAT', isTrashed: false, status: 'ACTIVE' } as Channel;
const fb = { id: 'c3', channelType: 'FACEBOOK', isTrashed: false, status: 'ACTIVE' } as Channel;

const onReplaceToken = vi.fn();

async function replaceTokenAction() {
  const { useChannelActions } = await import('./use-channel-actions');
  const useActions = useChannelActions as unknown as (o: { onReplaceToken: (c: Channel) => void }) => ReturnType<typeof useChannelActions>;
  const { result } = renderHook(() => useActions({ onReplaceToken }));
  return { all: result.current, action: result.current.find((a) => a.id === 'replace-token') };
}

describe('replace-token action - AC-42-20', () => {
  it('control: the registry still has its existing actions', async () => {
    const { all } = await replaceTokenAction();
    expect(all.map((a) => a.id)).toEqual(expect.arrayContaining(['edit', 'test-connection', 'disconnect']));
  });

  it('exists, is gated by channels.manage and surfaces on the row and the detail menu', async () => {
    const { action } = await replaceTokenAction();
    expect(action).toBeDefined();
    expect(action?.permission).toBe('channels.manage');
    expect(action?.surfaces.row).toBe(true);
    expect(action?.surfaces.form).toBe(true);
    expect(action?.label).toBe('Replace token');
  });

  it('opens a dialog through run (not a confirm, not a deferred action)', async () => {
    const { action } = await replaceTokenAction();
    expect(typeof action?.run).toBe('function');
    expect(action).not.toHaveProperty('confirm');
    expect(action).not.toHaveProperty('deferred');
  });

  it('is visible for a WhatsApp channel and not for other channel types', async () => {
    const { action } = await replaceTokenAction();
    expect(action?.isVisible?.([wa])).toBe(true);
    expect(action?.isVisible?.([web])).toBe(false);
    expect(action?.isVisible?.([fb])).toBe(false);
  });
});

describe('replace-token action wiring (review round)', () => {
  it('run hands the channel to onReplaceToken, like onConnect on the list config', async () => {
    onReplaceToken.mockClear();
    const { action } = await replaceTokenAction();
    await action?.run?.([wa], { reload: vi.fn() });
    expect(onReplaceToken).toHaveBeenCalledTimes(1);
    expect(onReplaceToken).toHaveBeenCalledWith(wa);
  });

  it('the module-level replace-token store is gone', () => {
    expect(existsSync(join(process.cwd(), 'app/(protected)/omnichannel/settings/channels/components/replace-token-store.ts'))).toBe(false);
  });
});

describe('channel service - AC-42-25', () => {
  it('exposes replaceChannelToken(id, accessToken)', async () => {
    const { channelService } = await import('@/services/channel-service');
    expect(typeof (channelService as unknown as Record<string, unknown>).replaceChannelToken).toBe('function');
  });
});
