'use client';

import { SearchSelect } from '@/components/platform/search-select';
import type { MigrationTargetStage } from '@/types/respondio-migration';

const NO_STAGE_VALUE = '__no_stage__';

/**
 * One Lifecycle-section row (AC-MIG-06): a source lifecycle label maps to an
 * EXISTING target-workspace stage only - the surface never offers to create
 * one. An unmapped label is allowed (contacts land with no lifecycle) and is
 * reported as a blocker in the dry-run report, not blocked here.
 */
export function LifecycleMapRow({
  sourceLabel,
  targetStages,
  value,
  editing,
  onChange,
}: {
  sourceLabel: string;
  targetStages: MigrationTargetStage[];
  value: string | null;
  editing: boolean;
  onChange: (targetStatusId: string | null) => void;
}) {
  const options = [
    { label: 'No lifecycle', value: NO_STAGE_VALUE },
    ...targetStages.map((s) => ({ label: s.label, value: s.statusId })),
  ];

  return (
    <div className="flex flex-col gap-1.5 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
      <p className="min-w-0 truncate text-sm font-medium">{sourceLabel}</p>
      <div className="w-full sm:max-w-xs">
        <SearchSelect
          ariaLabel={`Target lifecycle stage for ${sourceLabel}`}
          options={options}
          value={value ?? NO_STAGE_VALUE}
          disabled={!editing}
          onChange={(next) => onChange(next === NO_STAGE_VALUE ? null : next)}
        />
      </div>
    </div>
  );
}
