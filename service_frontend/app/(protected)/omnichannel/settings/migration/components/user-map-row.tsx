'use client';

import { SearchSelect } from '@/components/platform/search-select';
import { ClampedText } from '@/components/platform/clamped-text';

const UNASSIGNED_VALUE = '__unassigned__';

/**
 * One People-section row (AC-MIG-05). Generic over a labelled source entry
 * (a respond.io user OR a respond.io team - same shape, same rule: a
 * `SearchSelect` of the tenant's own users/teams, no free-text id entry
 * anywhere) rather than forking a parallel `team-map-row.tsx`.
 */
export function UserMapRow({
  label,
  sublabel,
  options,
  value,
  editing,
  onChange,
  ariaLabel,
}: {
  label: string;
  sublabel?: string;
  options: { label: string; value: string }[];
  value: string | null;
  editing: boolean;
  onChange: (targetId: string | null) => void;
  ariaLabel: string;
}) {
  const allOptions = [{ label: 'Unassigned', value: UNASSIGNED_VALUE }, ...options];

  return (
    <div className="flex flex-col gap-1.5 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
      <div className="min-w-0">
        <ClampedText text={label} lines={1} className="text-sm font-medium" />
        {sublabel && <ClampedText text={sublabel} lines={1} className="text-muted-foreground text-xs" />}
      </div>
      <div className="w-full sm:max-w-xs">
        <SearchSelect
          ariaLabel={ariaLabel}
          options={allOptions}
          value={value ?? UNASSIGNED_VALUE}
          disabled={!editing}
          onChange={(next) => onChange(next === UNASSIGNED_VALUE ? null : next)}
        />
      </div>
    </div>
  );
}
