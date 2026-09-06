import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api-client';
import type { BusinessHours } from '@/types/omnichannel';

const { getMock, updateMock } = vi.hoisted(() => ({
  getMock: vi.fn(),
  updateMock: vi.fn(),
}));
vi.mock('@/services/business-hours-service', () => ({
  businessHoursService: { get: getMock, update: updateMock },
}));

import { useBusinessHours } from './use-business-hours';

function loaded(over: Partial<BusinessHours> = {}): BusinessHours {
  return {
    workspaceId: 'wsp-001',
    timezone: 'Asia/Kuala_Lumpur',
    windows: {
      mon: [{ from: '09:00', to: '18:00' }],
      tue: [],
      wed: [],
      thu: [],
      fri: [],
      sat: [],
      sun: [],
    },
    ...over,
  };
}

beforeEach(() => {
  getMock.mockReset();
  updateMock.mockReset();
});

describe('useBusinessHours', () => {
  it('loads and starts clean (not dirty)', async () => {
    getMock.mockResolvedValue(loaded());
    const { result } = renderHook(() => useBusinessHours('wsp-001'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.timezone).toBe('Asia/Kuala_Lumpur');
    expect(result.current.isDirty).toBe(false);
  });

  it('becomes dirty when the timezone or a window changes', async () => {
    getMock.mockResolvedValue(loaded());
    const { result } = renderHook(() => useBusinessHours('wsp-001'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => result.current.setTimezone('UTC'));
    expect(result.current.isDirty).toBe(true);
  });

  it('save() persists and re-syncs the baseline from the response, clearing dirty', async () => {
    getMock.mockResolvedValue(loaded());
    const saved = loaded({ timezone: 'UTC' });
    updateMock.mockResolvedValue(saved);
    const { result } = renderHook(() => useBusinessHours('wsp-001'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => result.current.setTimezone('UTC'));
    let ok = false;
    await act(async () => {
      ok = await result.current.save();
    });
    expect(ok).toBe(true);
    expect(updateMock).toHaveBeenCalledWith('wsp-001', {
      timezone: 'UTC',
      windows: loaded().windows,
    });
    expect(result.current.isDirty).toBe(false);
  });

  it('save() on a 422 returns false and surfaces fieldErrors without clearing dirty', async () => {
    getMock.mockResolvedValue(loaded());
    updateMock.mockRejectedValue(
      new ApiError('Business hours validation failed', 422, null, {
        fieldErrors: { 'windows.mon.0': 'End time must differ from the start time.' },
      }),
    );
    const { result } = renderHook(() => useBusinessHours('wsp-001'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => result.current.setTimezone('UTC'));
    let ok = true;
    await act(async () => {
      ok = await result.current.save();
    });
    expect(ok).toBe(false);
    expect(result.current.fieldErrors['windows.mon.0']).toBe(
      'End time must differ from the start time.',
    );
    expect(result.current.isDirty).toBe(true);
  });

  it('discard() reverts to the loaded baseline', async () => {
    getMock.mockResolvedValue(loaded());
    const { result } = renderHook(() => useBusinessHours('wsp-001'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => result.current.setTimezone('UTC'));
    expect(result.current.isDirty).toBe(true);
    act(() => result.current.discard());
    expect(result.current.timezone).toBe('Asia/Kuala_Lumpur');
    expect(result.current.isDirty).toBe(false);
  });

  it('save() is a no-op when nothing changed (no network call)', async () => {
    getMock.mockResolvedValue(loaded());
    const { result } = renderHook(() => useBusinessHours('wsp-001'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    let ok = false;
    await act(async () => {
      ok = await result.current.save();
    });
    expect(ok).toBe(true);
    expect(updateMock).not.toHaveBeenCalled();
  });
});
