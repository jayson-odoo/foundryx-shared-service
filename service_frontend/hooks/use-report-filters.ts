'use client';

/**
 * URL-synced filter state shared by the dashboard AND reports pages (plan 30,
 * AC-RPT-43) - ONE component's worth of state (date range, user, channel,
 * granularity, group-by) lives in the query string so a reload restores it.
 * Reads `window.location.search` directly rather than `useSearchParams()` (the
 * house convention on this branch - see the Inbox host) so the route stays
 * statically prerenderable; writes via `history.replaceState` (no history
 * spam per filter tweak).
 *
 * `groupBy` lives HERE, not inside a renderer (S-5, review round 1): it was
 * renderer-local `useState`, so the page's Export button - which builds its
 * request from `filters` - always exported the UNGROUPED shape no matter
 * which breakdown the user was looking at. Lifting it means the report
 * request and the export request are built from the one value.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { resolvePresetRange, type DateRangePreset, type DateRangeValue } from '@/components/platform/date-range-picker';
import { useDatetime } from '@/hooks/use-datetime';
import type { ReportFilters, ReportGranularity } from '@/types/omnichannel';

export interface ReportFilterState {
  dateRange: DateRangeValue;
  userId: string | null;
  channelId: string | null;
  /** `null` = auto-select from the range (server/mock default). */
  granularity: ReportGranularity | null;
  /** `null` = the report's own default (ungrouped) breakdown. */
  groupBy: string | null;
}

export interface UseReportFiltersResult {
  state: ReportFilterState;
  setDateRange: (value: DateRangeValue) => void;
  setUserId: (value: string | null) => void;
  setChannelId: (value: string | null) => void;
  setGranularity: (value: ReportGranularity | null) => void;
  setGroupBy: (value: string | null) => void;
  /** The state, shaped for `omnichannelReportService` calls. */
  filters: ReportFilters;
}

const DEFAULT_PRESET: DateRangePreset = 'last7';
const GRANULARITIES: ReportGranularity[] = ['hour', 'day', 'week', 'month'];

function readFromUrl(timeZone: string): ReportFilterState {
  if (typeof window === 'undefined') {
    return {
      dateRange: { preset: DEFAULT_PRESET, ...resolvePresetRange(DEFAULT_PRESET, timeZone) },
      userId: null,
      channelId: null,
      granularity: null,
      groupBy: null,
    };
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
    groupBy: params.get('groupBy'),
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
  set('groupBy', state.groupBy);
  window.history.replaceState(null, '', url);
}

export function useReportFilters(): UseReportFiltersResult {
  const { timeZone } = useDatetime();
  const [state, setState] = useState<ReportFilterState>(() => readFromUrl(timeZone));

  useEffect(() => {
    writeToUrl(state);
  }, [state]);

  // Stable setter identities so a consumer effect (e.g. the reports page
  // clearing an unsupported `groupBy` on report switch) doesn't resubscribe
  // on every render.
  const setDateRange = useCallback((dateRange: DateRangeValue) => setState((s) => ({ ...s, dateRange })), []);
  const setUserId = useCallback((userId: string | null) => setState((s) => ({ ...s, userId })), []);
  const setChannelId = useCallback((channelId: string | null) => setState((s) => ({ ...s, channelId })), []);
  const setGranularity = useCallback(
    (granularity: ReportGranularity | null) => setState((s) => ({ ...s, granularity })),
    [],
  );
  const setGroupBy = useCallback(
    (groupBy: string | null) => setState((s) => (s.groupBy === groupBy ? s : { ...s, groupBy })),
    [],
  );

  const filters: ReportFilters = useMemo(
    () => ({
      from: state.dateRange.from,
      to: state.dateRange.to,
      tz: timeZone,
      granularity: state.granularity ?? undefined,
      userId: state.userId ?? undefined,
      channelId: state.channelId ?? undefined,
      groupBy: state.groupBy ?? undefined,
    }),
    [state, timeZone],
  );

  return { state, setDateRange, setUserId, setChannelId, setGranularity, setGroupBy, filters };
}
