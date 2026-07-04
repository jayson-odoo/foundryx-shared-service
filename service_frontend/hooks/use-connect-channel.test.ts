import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { Channel, MockWabaOption } from '@/types/omnichannel';
import { useConnectChannel } from './use-connect-channel';

const completeOnboarding = vi.fn();

vi.mock('@/services/onboarding-service', () => ({
  onboardingService: {
    completeOnboarding: (...args: unknown[]) => completeOnboarding(...args),
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
