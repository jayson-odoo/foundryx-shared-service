'use client';

/**
 * Shared filter bar (plan 30, AC-RPT-43) - ONE component rendered by both the
 * Dashboard and Reports pages. Date range / user / channel / granularity,
 * every control a `SearchSelect`. The team control is ABSENT while
 * `dimensions.team.available` is false (D-A9-13) - never rendered disabled,
 * never rendered at all, so there is nothing to explain.
 */
import { DateRangePicker, type DateRangeValue } from '@/components/platform/date-range-picker';
import { SearchSelect, type SearchSelectOption } from '@/components/platform/search-select';
import { cn } from '@/lib/utils';
import type { ReportGranularity } from '@/types/omnichannel';

const ALL_USERS = 'all';
const ALL_CHANNELS = 'all';

const GRANULARITY_LABEL: Record<ReportGranularity, string> = {
  hour: 'Hourly',
  day: 'Daily',
  week: 'Weekly',
  month: 'Monthly',
};

export interface ReportFilterBarMember {
  id: string;
  name: string;
}

export interface ReportFilterBarChannel {
  id: string;
  name: string;
}

export interface ReportFilterBarProps {
  dateRange: DateRangeValue;
  onDateRangeChange: (value: DateRangeValue) => void;
  timeZone: string;
  userId: string | null;
  onUserIdChange: (value: string | null) => void;
  members: ReportFilterBarMember[];
  channelId: string | null;
  onChannelIdChange: (value: string | null) => void;
  channels: ReportFilterBarChannel[];
  granularity: ReportGranularity | null;
  onGranularityChange: (value: ReportGranularity | null) => void;
  granularityOptions: ReportGranularity[];
  className?: string;
}

export function ReportFilterBar({
  dateRange,
  onDateRangeChange,
  timeZone,
  userId,
  onUserIdChange,
  members,
  channelId,
  onChannelIdChange,
  channels,
  granularity,
  onGranularityChange,
  granularityOptions,
  className,
}: ReportFilterBarProps) {
  const userOptions: SearchSelectOption[] = [
    { label: 'All users', value: ALL_USERS },
    ...members.map((m) => ({ label: m.name, value: m.id })),
  ];
  const channelOptions: SearchSelectOption[] = [
    { label: 'All channels', value: ALL_CHANNELS },
    ...channels.map((c) => ({ label: c.name, value: c.id })),
  ];
  const granularitySelectOptions: SearchSelectOption[] = granularityOptions.map((g) => ({
    label: GRANULARITY_LABEL[g],
    value: g,
  }));

  return (
    <div className={cn('flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center', className)}>
      <DateRangePicker value={dateRange} onChange={onDateRangeChange} timeZone={timeZone} className="w-full sm:w-auto" />
      <SearchSelect
        ariaLabel="User"
        className="w-full sm:w-44"
        value={userId ?? ALL_USERS}
        onChange={(v) => onUserIdChange(v === ALL_USERS ? null : v)}
        options={userOptions}
      />
      <SearchSelect
        ariaLabel="Channel"
        className="w-full sm:w-44"
        value={channelId ?? ALL_CHANNELS}
        onChange={(v) => onChannelIdChange(v === ALL_CHANNELS ? null : v)}
        options={channelOptions}
      />
      <SearchSelect
        ariaLabel="Granularity"
        className="w-full sm:w-36"
        value={granularity ?? 'auto'}
        onChange={(v) => onGranularityChange(v === 'auto' ? null : (v as ReportGranularity))}
        options={[{ label: 'Auto', value: 'auto' }, ...granularitySelectOptions]}
      />
    </div>
  );
}
