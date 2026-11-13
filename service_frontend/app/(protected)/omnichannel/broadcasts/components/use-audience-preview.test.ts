/**
 * Audience preview hook (plan 29 S4, AC-BRD-05) - debounces the resolved
 * recipient count against the REAL `broadcastService.audiencePreview` POST,
 * and never calls it for an audience that isn't resolvable yet (no segment /
 * empty filter / no contacts chosen - the same `isResolvable` gate the
 * builder's Review section relies on to show "-" instead of a bogus 0).
 */
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { BroadcastAudience } from '@/types/omnichannel';
import { useAudiencePreview } from './use-audience-preview';

const audiencePreviewMock = vi.fn();
vi.mock('@/services/broadcast-service', () => ({
  broadcastService: {
    audiencePreview: (...args: unknown[]) => audiencePreviewMock(...args),
  },
}));

beforeEach(() => {
  vi.useFakeTimers();
  audiencePreviewMock.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('useAudiencePreview', () => {
  it('never calls the service for an unresolvable audience (no segment chosen yet)', () => {
    const audience: BroadcastAudience = { kind: 'segment' };
    const { result } = renderHook(() => useAudiencePreview('wsp-1', audience));
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(audiencePreviewMock).not.toHaveBeenCalled();
    expect(result.current.count).toBeNull();
  });

  it('never calls the service for a filter audience with zero conditions', () => {
    const audience: BroadcastAudience = {
      kind: 'filter',
      filter: { kind: 'group', combinator: 'and', rules: [] },
    };
    renderHook(() => useAudiencePreview('wsp-1', audience));
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(audiencePreviewMock).not.toHaveBeenCalled();
  });

  it('debounces a resolvable audience and reports the resolved count', async () => {
    audiencePreviewMock.mockResolvedValue({ count: 42 });
    const audience: BroadcastAudience = { kind: 'contacts', contactIds: ['cnt-1', 'cnt-2'] };
    const { result } = renderHook(() => useAudiencePreview('wsp-1', audience));

    // Not yet fired before the debounce window.
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(audiencePreviewMock).not.toHaveBeenCalled();

    await act(async () => {
      vi.advanceTimersByTime(200);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(result.current.count).toBe(42);
    expect(audiencePreviewMock).toHaveBeenCalledWith('wsp-1', audience);
  });

  it('resolves to null (not a stale count) when the service call fails', async () => {
    audiencePreviewMock.mockRejectedValue(new Error('boom'));
    const audience: BroadcastAudience = { kind: 'contacts', contactIds: ['cnt-1'] };
    const { result } = renderHook(() => useAudiencePreview('wsp-1', audience));

    await act(async () => {
      vi.advanceTimersByTime(400);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(result.current.loading).toBe(false);
    expect(result.current.count).toBeNull();
  });
});
