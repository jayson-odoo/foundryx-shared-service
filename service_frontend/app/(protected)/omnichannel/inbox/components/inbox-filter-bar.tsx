'use client';

/**
 * List-header Show / Sort / Unreplied controls (plan 27, AC-IVE-21). Replaces
 * the two bare `<Select>`s `thread-list.tsx` used to render (status +
 * priority) - every dropdown is searchable (design mandate).
 */
import { SearchSelect, type SearchSelectOption } from '@/components/platform/search-select';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
import type { ConversationFilters } from '@/hooks/use-conversations';
import { cn } from '@/lib/utils';
import type { ThreadPriority, ThreadSort, ThreadStatus } from '@/types/omnichannel';

const SHOW_OPTIONS: SearchSelectOption[] = [
  { label: 'All', value: 'ALL' },
  { label: 'Open', value: 'OPEN' },
  { label: 'Snoozed', value: 'SNOOZED' },
  { label: 'Closed', value: 'CLOSED' },
];

const SORT_OPTIONS: SearchSelectOption[] = [
  { label: 'Newest', value: 'newest' },
  { label: 'Oldest', value: 'oldest' },
  { label: 'Unreplied first', value: 'unreplied_first' },
  { label: 'Longest waiting', value: 'longest_waiting' },
];

const PRIORITY_OPTIONS: SearchSelectOption[] = [
  { label: 'All priorities', value: 'ALL' },
  { label: 'Urgent', value: 'URGENT' },
  { label: 'High', value: 'HIGH' },
  { label: 'Medium', value: 'MEDIUM' },
  { label: 'Low', value: 'LOW' },
];

export interface InboxFilterBarProps {
  filters: ConversationFilters;
  setFilters: (patch: Partial<ConversationFilters>) => void;
  className?: string;
}

export function InboxFilterBar({ filters, setFilters, className }: InboxFilterBarProps) {
  return (
    <div className={cn('flex flex-wrap items-center gap-2', className)} data-testid="inbox-filter-bar">
      <SearchSelect
        options={SHOW_OPTIONS}
        value={filters.status}
        onChange={(v) => setFilters({ status: v as ThreadStatus | 'ALL' })}
        ariaLabel="Show"
        className="w-28"
      />
      <SearchSelect
        options={SORT_OPTIONS}
        value={filters.sort}
        onChange={(v) => setFilters({ sort: v as ThreadSort })}
        ariaLabel="Sort"
        className="w-40"
      />
      <SearchSelect
        options={PRIORITY_OPTIONS}
        value={filters.priority}
        onChange={(v) => setFilters({ priority: v as ThreadPriority | 'ALL' })}
        ariaLabel="Priority filter"
        className="w-32"
      />
      <div className="ms-auto flex items-center gap-1.5">
        <Switch
          id="inbox-unreplied"
          checked={filters.unreplied}
          onCheckedChange={(v) => setFilters({ unreplied: v })}
          data-testid="inbox-unreplied"
        />
        <Label htmlFor="inbox-unreplied" className="cursor-pointer text-sm">
          Unreplied
        </Label>
      </div>
    </div>
  );
}
