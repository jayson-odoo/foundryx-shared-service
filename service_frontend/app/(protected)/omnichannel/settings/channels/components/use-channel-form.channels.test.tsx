/**
 * Channel form tab filtering (plan 32 / A7a, AC-CHN-05, AC-CHN-61) - Templates
 * + Profile are absent for a Messenger/Instagram channel (WABA/WhatsApp
 * concepts), exactly the way `webhooks` is already conditional.
 */
import { renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { Channel, ChannelProfile } from '@/types/omnichannel';
import { useChannelForm } from './use-channel-form';

vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true, permissions: new Set<string>() }),
}));

const EMPTY_PROFILE: ChannelProfile = {
  about: null,
  address: null,
  description: null,
  email: null,
  vertical: null,
  website1: null,
  website2: null,
  profilePictureUrl: null,
  profileSyncedAt: null,
};

function channel(over: Partial<Channel> = {}): Channel {
  return {
    id: 'chn-1',
    tenantId: 'default',
    workspaceId: 'wsp-1',
    workspaceName: 'General',
    channelType: 'WHATSAPP',
    name: 'Test channel',
    status: 'ACTIVE',
    isActive: true,
    wabaId: null,
    phoneNumberId: null,
    displayPhoneNumber: null,
    businessAccountName: null,
    verifiedName: null,
    lastVerifiedAt: null,
    profileSyncedAt: null,
    externalAccountId: null,
    externalAccountName: null,
    isTrashed: false,
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
    ...over,
  };
}

vi.mock('@/services/channel-service', () => ({
  channelService: {
    get: (id: string) => Promise.resolve(channelStore[id]),
    getProfile: () => Promise.resolve(EMPTY_PROFILE),
  },
}));

let channelStore: Record<string, Channel> = {};

describe('useChannelForm - tab filtering by channel type', () => {
  it('WhatsApp keeps Configuration, Templates and Profile', async () => {
    channelStore = { 'chn-1': channel({ channelType: 'WHATSAPP' }) };
    const { result } = renderHook(() => useChannelForm('chn-1', false));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    const ids = result.current.config?.tabs.map((t) => t.id);
    expect(ids).toEqual(expect.arrayContaining(['configuration', 'templates', 'profile']));
  });

  it('Messenger filters out Templates and Profile (WABA-only concepts)', async () => {
    channelStore = { 'chn-fb-1': channel({ id: 'chn-fb-1', channelType: 'FACEBOOK' }) };
    const { result } = renderHook(() => useChannelForm('chn-fb-1', false));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    const ids = result.current.config?.tabs.map((t) => t.id) ?? [];
    expect(ids).toContain('configuration');
    expect(ids).not.toContain('templates');
    expect(ids).not.toContain('profile');
  });

  it('Instagram filters out Templates and Profile too', async () => {
    channelStore = { 'chn-ig-1': channel({ id: 'chn-ig-1', channelType: 'INSTAGRAM' }) };
    const { result } = renderHook(() => useChannelForm('chn-ig-1', false));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    const ids = result.current.config?.tabs.map((t) => t.id) ?? [];
    expect(ids).not.toContain('templates');
    expect(ids).not.toContain('profile');
  });
});
