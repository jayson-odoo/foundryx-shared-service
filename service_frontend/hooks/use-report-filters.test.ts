import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { timezone: 'Asia/Kuala_Lumpur' } }, status: 'authenticated' }),
}));

import { useReportFilters } from './use-report-filters';

function setUrl(search: string): void {
  window.history.replaceState(null, '', `/omnichannel/dashboard${search}`);
}

describe('useReportFilters', () => {
  beforeEach(() => {
    setUrl('');
  });

  it('defaults to the Last 7 days preset resolved in the session timezone', () => {
    const { result } = renderHook(() => useReportFilters());
    expect(result.current.state.dateRange.preset).toBe('last7');
    expect(result.current.filters.tz).toBe('Asia/Kuala_Lumpur');
    expect(result.current.state.dateRange.from <= result.current.state.dateRange.to).toBe(true);
  });

  it('restores an explicit range/user/channel/granularity from the URL', () => {
    setUrl('?preset=custom&from=2026-03-01&to=2026-03-07&userId=u_ann&channelId=chn-wa&granularity=week');
    const { result } = renderHook(() => useReportFilters());
    expect(result.current.state.dateRange).toEqual({ preset: 'custom', from: '2026-03-01', to: '2026-03-07' });
    expect(result.current.filters).toMatchObject({
      from: '2026-03-01',
      to: '2026-03-07',
      userId: 'u_ann',
      channelId: 'chn-wa',
      granularity: 'week',
    });
  });

  it('ignores an unknown granularity value from a tampered URL', () => {
    setUrl('?from=2026-03-01&to=2026-03-07&granularity=fortnight');
    const { result } = renderHook(() => useReportFilters());
    expect(result.current.state.granularity).toBeNull();
    expect(result.current.filters.granularity).toBeUndefined();
  });

  it('writes every change back to the URL (reload restores it)', () => {
    const { result } = renderHook(() => useReportFilters());
    act(() => {
      result.current.setUserId('u_ben');
      result.current.setChannelId('chn-wa');
      result.current.setGranularity('day');
    });
    const params = new URLSearchParams(window.location.search);
    expect(params.get('userId')).toBe('u_ben');
    expect(params.get('channelId')).toBe('chn-wa');
    expect(params.get('granularity')).toBe('day');
  });

  it('switching the date range updates state and filters together', () => {
    const { result } = renderHook(() => useReportFilters());
    act(() => {
      result.current.setDateRange({ preset: 'thisMonth', from: '2026-03-01', to: '2026-03-15' });
    });
    expect(result.current.filters.from).toBe('2026-03-01');
    expect(result.current.filters.to).toBe('2026-03-15');
    expect(new URLSearchParams(window.location.search).get('preset')).toBe('thisMonth');
  });
});
