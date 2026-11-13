/**
 * Channel form tab filtering (plan 32 / A7a, AC-CHN-05, AC-CHN-61; plan 34 /
 * A7b, AC-WEB-03) - Templates + Profile are absent for a Messenger/Instagram
 * or Web chat channel (WABA/WhatsApp concepts), exactly the way `webhooks`
 * is already conditional; a Web chat channel gains a Widget tab instead.
 */
import { renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { Channel, ChannelProfile, WebchatConfig } from '@/types/omnichannel';
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
    widgetKey: null,
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

const WEBCHAT_CONFIG: WebchatConfig = {
  widgetKey: 'wk_test0000000000000000000001',
  allowedOrigins: ['https://shop.acme.test'],
  tokenEpoch: 0,
  appearance: { accentColor: '#FF5A00', position: 'right', headerTitle: 'Chat', agentDisplayName: 'Support' },
  greeting: 'Hi!',
  offlineGreeting: 'Offline',
  preChat: { askName: true, askEmail: true, askPhone: false },
  snippet: '<script src="https://app.example/omnichannel/widget/wk_test.js" async></script>',
};

vi.mock('@/services/webchat-service', () => ({
  webchatService: {
    getConfig: () => Promise.resolve(WEBCHAT_CONFIG),
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

  it('Web chat gains a Widget tab and filters out Templates and Profile (AC-WEB-03)', async () => {
    channelStore = { 'chn-web-1': channel({ id: 'chn-web-1', channelType: 'WEBCHAT', widgetKey: WEBCHAT_CONFIG.widgetKey }) };
    const { result } = renderHook(() => useChannelForm('chn-web-1', false));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    const ids = result.current.config?.tabs.map((t) => t.id) ?? [];
    expect(ids).toContain('configuration');
    expect(ids).toContain('widget');
    expect(ids).not.toContain('templates');
    expect(ids).not.toContain('profile');
  });
});
