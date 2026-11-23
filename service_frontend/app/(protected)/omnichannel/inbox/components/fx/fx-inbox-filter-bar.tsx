'use client';

/**
 * Show / Sort / Priority and Unreplied with the Foundryx UIUX switch on
 * (slice W1-INBOX): the playbook dropdowns (`SearchSelect` draws them under
 * the switch) and the playbook on/off switch. Same options and the same
 * filter changes as the legacy bar, so the list requests are identical.
 */
import type {
  ThreadPriority,
  ThreadSort,
  ThreadStatus,
} from '@/types/omnichannel';
import { cn } from '@/lib/utils';
import { Switch } from '@/components/ui/switch';
import { SearchSelect } from '@/components/platform/search-select';
import {
  PRIORITY_OPTIONS,
  SHOW_OPTIONS,
  SORT_OPTIONS,
  type InboxFilterBarProps,
} from '../inbox-filter-bar';

export function FxInboxFilterBar({
  filters,
  setFilters,
  className,
}: InboxFilterBarProps) {
  return (
    <div
      className={cn('flex flex-wrap items-center gap-2', className)}
      data-testid="inbox-filter-bar"
      data-fx-inbox-filters=""
    >
      <SearchSelect
        options={SHOW_OPTIONS}
        value={filters.status}
        onChange={(v) =>
          setFilters({
            status: v as ThreadStatus | 'ALL',
            statusExplicit: true,
          })
        }
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
        className="w-36"
      />
      <label className="ms-auto inline-flex min-h-9 cursor-pointer items-center gap-2 text-sm font-semibold text-(--fx-ink-2)">
        <Switch
          checked={filters.unreplied}
          onCheckedChange={(v) => setFilters({ unreplied: v })}
          aria-label="Unreplied only"
          data-testid="inbox-unreplied"
        />
        Unreplied
      </label>
    </div>
  );
}
