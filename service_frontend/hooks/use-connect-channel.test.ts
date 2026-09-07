import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api-client';
import type { Channel, MetaPageOption, MockWabaOption } from '@/types/omnichannel';
import { useConnectChannel } from './use-connect-channel';

const completeOnboarding = vi.fn();
const listMetaPages = vi.fn();
const connectMetaChannel = vi.fn();

vi.mock('@/services/onboarding-service', () => ({
  onboardingService: {
    completeOnboarding: (...args: unknown[]) => completeOnboarding(...args),
    manualConnect: vi.fn(),
    listMetaPages: (...args: unknown[]) => listMetaPages(...args),
    connectMetaChannel: (...args: unknown[]) => connectMetaChannel(...args),
  },
}));

const OPTION: MockWabaOption = {
  wabaId: 'waba-1',
  businessName: 'Acme',
  phoneNumberId: 'pn-1',
  displayPhoneNumber: '+65 8000 0000',
};

const CHANNEL = { id: 'chn-9', name: 'Acme', displayPhoneNumber: '+65 8000 0000' } as Channel;

describe('useConnectChannel (wizard state machine)', () => {
  it('starts idle and opens the popup on start()', () => {
    const { result } = renderHook(() => useConnectChannel('wsp-1'));
    expect(result.current.state).toBe('idle');
    act(() => result.current.start());
    expect(result.current.state).toBe('selecting');
  });

  it('cancel() returns to idle', () => {
    const { result } = renderHook(() => useConnectChannel('wsp-1'));
    act(() => result.current.start());
    act(() => result.current.cancel());
    expect(result.current.state).toBe('idle');
  });

  it('authorize() → exchanging → connected, carrying the channel', async () => {
    completeOnboarding.mockResolvedValue(CHANNEL);
    const { result } = renderHook(() => useConnectChannel('wsp-1'));
    act(() => result.current.start());
    await act(async () => {
      await result.current.authorize(OPTION);
    });
    await waitFor(() => expect(result.current.state).toBe('connected'));
    expect(result.current.channel).toEqual(CHANNEL);
    expect(completeOnboarding).toHaveBeenCalledWith(
      'wsp-1',
      expect.objectContaining({ wabaId: 'waba-1', phoneNumberId: 'pn-1' }),
    );
  });

  it('authorize() failure → failed with an error message', async () => {
    completeOnboarding.mockRejectedValue(new Error('boom'));
    const { result } = renderHook(() => useConnectChannel('wsp-1'));
    act(() => result.current.start());
    await act(async () => {
      await result.current.authorize(OPTION);
    });
    await waitFor(() => expect(result.current.state).toBe('failed'));
    expect(result.current.error).toBe('boom');
  });

  it('reset() clears state back to idle', async () => {
    completeOnboarding.mockResolvedValue(CHANNEL);
    const { result } = renderHook(() => useConnectChannel('wsp-1'));
    act(() => result.current.start());
    await act(async () => {
      await result.current.authorize(OPTION);
    });
    act(() => result.current.reset());
    expect(result.current.state).toBe('idle');
    expect(result.current.channel).toBeNull();
  });
});

describe('useConnectChannel - Messenger/Instagram (plan 32 / A7a)', () => {
  const PAGE: MetaPageOption = { id: 'pg-1', name: 'Acme Page', connected: false };
  const META_CHANNEL = { id: 'chn-fb-1', name: 'Acme Page (Messenger)' } as Channel;

  it('startMetaAuth() -> authorizing, never entering the WhatsApp "selecting" state', () => {
    const { result } = renderHook(() => useConnectChannel('wsp-1'));
    act(() => result.current.startMetaAuth());
    expect(result.current.state).toBe('authorizing');
  });

  it('authorizeMetaCode() exchanges the code for pages -> picking-page', async () => {
    listMetaPages.mockResolvedValue({ sessionId: 'sess-1', expiresAt: '2026-01-01T00:05:00Z', pages: [PAGE] });
    const { result } = renderHook(() => useConnectChannel('wsp-1'));
    act(() => result.current.startMetaAuth());
    await act(async () => {
      await result.current.authorizeMetaCode('FACEBOOK', 'code-1', 'https://app/callback');
    });
    expect(result.current.state).toBe('picking-page');
    expect(result.current.pages).toEqual([PAGE]);
    expect(listMetaPages).toHaveBeenCalledWith({
      channelType: 'FACEBOOK',
      code: 'code-1',
      redirectUri: 'https://app/callback',
    });
  });

  it('selectMetaPage() finalizes the connect -> connected, carrying the session id', async () => {
    listMetaPages.mockResolvedValue({ sessionId: 'sess-2', expiresAt: '2026-01-01T00:05:00Z', pages: [PAGE] });
    connectMetaChannel.mockResolvedValue(META_CHANNEL);
    const { result } = renderHook(() => useConnectChannel('wsp-1'));
    act(() => result.current.startMetaAuth());
    await act(async () => {
      await result.current.authorizeMetaCode('FACEBOOK', 'code-1');
    });
    await act(async () => {
      await result.current.selectMetaPage('FACEBOOK', 'wsp-1', PAGE);
    });
    await waitFor(() => expect(result.current.state).toBe('connected'));
    expect(result.current.channel).toEqual(META_CHANNEL);
    expect(connectMetaChannel).toHaveBeenCalledWith(
      expect.objectContaining({ sessionId: 'sess-2', pageId: 'pg-1', channelType: 'FACEBOOK' }),
    );
  });

  it('a typed connect-session-expired 400 maps to friendly copy, not a bare status line', async () => {
    listMetaPages.mockResolvedValue({ sessionId: 'sess-3', expiresAt: '2026-01-01T00:05:00Z', pages: [PAGE] });
    connectMetaChannel.mockRejectedValue(
      new ApiError('Bad Request', 400, undefined, { reason: 'connect_session_expired' }),
    );
    const { result } = renderHook(() => useConnectChannel('wsp-1'));
    act(() => result.current.startMetaAuth());
    await act(async () => {
      await result.current.authorizeMetaCode('FACEBOOK', 'code-1');
    });
    await act(async () => {
      await result.current.selectMetaPage('FACEBOOK', 'wsp-1', PAGE);
    });
    await waitFor(() => expect(result.current.state).toBe('failed'));
    expect(result.current.error).toBe('This connection attempt has expired - start again.');
  });

  it('a typed external-account-in-use 409 maps to friendly copy', async () => {
    listMetaPages.mockResolvedValue({ sessionId: 'sess-4', expiresAt: '2026-01-01T00:05:00Z', pages: [PAGE] });
    connectMetaChannel.mockRejectedValue(
      new ApiError('Conflict', 409, undefined, { reason: 'external_account_in_use' }),
    );
    const { result } = renderHook(() => useConnectChannel('wsp-1'));
    act(() => result.current.startMetaAuth());
    await act(async () => {
      await result.current.authorizeMetaCode('FACEBOOK', 'code-1');
    });
    await act(async () => {
      await result.current.selectMetaPage('FACEBOOK', 'wsp-1', PAGE);
    });
    await waitFor(() => expect(result.current.state).toBe('failed'));
    expect(result.current.error).toBe('This page is already connected to another channel.');
  });

  it('a failed page exchange surfaces an error and never reaches picking-page', async () => {
    listMetaPages.mockRejectedValue(new Error('OAuth code invalid'));
    const { result } = renderHook(() => useConnectChannel('wsp-1'));
    act(() => result.current.startMetaAuth());
    await act(async () => {
      await result.current.authorizeMetaCode('FACEBOOK', 'bad-code');
    });
    await waitFor(() => expect(result.current.state).toBe('failed'));
    expect(result.current.error).toBe('OAuth code invalid');
  });
});
