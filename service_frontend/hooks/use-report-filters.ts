'use client';

/**
 * URL-synced filter state shared by the dashboard AND reports pages (plan 30,
 * AC-RPT-43) - ONE component's worth of state (date range, user, channel,
 * granularity) lives in the query string so a reload restores it. Reads
 * `window.location.search` directly rather than `useSearchParams()` (the
 * house convention on this branch - see the Inbox host) so the route stays
 * statically prerenderable; writes via `history.replaceState` (no history
 * spam per filter tweak).
 */
import { useEffect, useState } from 'react';
import { resolvePresetRange, type DateRangePreset, type DateRangeValue } from '@/components/platform/date-range-picker';
import { useDatetime } from '@/hooks/use-datetime';
import type { ReportFilters, ReportGranularity } from '@/types/omnichannel';

export interface ReportFilterState {
  dateRange: DateRangeValue;
  userId: string | null;
  channelId: string | null;
  /** `null` = auto-select from the range (server/mock default). */
  granularity: ReportGranularity | null;
}

export interface UseReportFiltersResult {
  state: ReportFilterState;
  setDateRange: (value: DateRangeValue) => void;
  setUserId: (value: string | null) => void;
  setChannelId: (value: string | null) => void;
  setGranularity: (value: ReportGranularity | null) => void;
  /** The state, shaped for `omnichannelReportService` calls. */
  filters: ReportFilters;
}

const DEFAULT_PRESET: DateRangePreset = 'last7';
const GRANULARITIES: ReportGranularity[] = ['hour', 'day', 'week', 'month'];

function readFromUrl(timeZone: string): ReportFilterState {
  if (typeof window === 'undefined') {
    return { dateRange: { preset: DEFAULT_PRESET, ...resolvePresetRange(DEFAULT_PRESET, timeZone) }, userId: null, channelId: null, granularity: null };
  }
  const params = new URLSearchParams(window.location.search);
  const from = params.get('from');
  const to = params.get('to');
  const presetParam = params.get('preset') as DateRangePreset | null;
  const dateRange: DateRangeValue =
    from && to
      ? { preset: presetParam ?? 'custom', from, to }
      : { preset: DEFAULT_PRESET, ...resolvePresetRange(DEFAULT_PRESET, timeZone) };
  const granularityParam = params.get('granularity') as ReportGranularity | null;
  return {
    dateRange,
    userId: params.get('userId'),
    channelId: params.get('channelId'),
    granularity: granularityParam && GRANULARITIES.includes(granularityParam) ? granularityParam : null,
  };
}

function writeToUrl(state: ReportFilterState): void {
  if (typeof window === 'undefined') return;
  const url = new URL(window.location.href);
  const set = (key: string, value: string | null | undefined) => {
    if (value) url.searchParams.set(key, value);
    else url.searchParams.delete(key);
  };
  set('preset', state.dateRange.preset);
  set('from', state.dateRange.from);
  set('to', state.dateRange.to);
  set('userId', state.userId);
  set('channelId', state.channelId);
  set('granularity', state.granularity);
  window.history.replaceState(null, '', url);
}

export function useReportFilters(): UseReportFiltersResult {
  const { timeZone } = useDatetime();
  const [state, setState] = useState<ReportFilterState>(() => readFromUrl(timeZone));

  useEffect(() => {
    writeToUrl(state);
  }, [state]);

  return {
    state,
    setDateRange: (dateRange) => setState((s) => ({ ...s, dateRange })),
    setUserId: (userId) => setState((s) => ({ ...s, userId })),
    setChannelId: (channelId) => setState((s) => ({ ...s, channelId })),
    setGranularity: (granularity) => setState((s) => ({ ...s, granularity })),
    filters: {
      from: state.dateRange.from,
      to: state.dateRange.to,
      tz: timeZone,
      granularity: state.granularity ?? undefined,
      userId: state.userId ?? undefined,
      channelId: state.channelId ?? undefined,
    },
  };
}
