'use client';

import { SearchSelect } from '@/components/platform/search-select';
import { ClampedText } from '@/components/platform/clamped-text';
import type { MigrationSourceChannel, MigrationTargetChannel } from '@/types/respondio-migration';

const SKIP_VALUE = '__skip__';

/**
 * One Channels-section row (AC-MIG-04): a source channel maps to a target
 * channel whose `channelType` is compatible with the source's respond.io
 * `source` value, or explicitly "Skip this channel". A source with zero
 * compatible targets renders with ONLY the Skip option - the picker never
 * offers a target that would silently misroute a channel's history.
 */
export function ChannelMapRow({
  channel,
  compatibleTargets,
  value,
  editing,
  onChange,
}: {
  channel: MigrationSourceChannel;
  compatibleTargets: MigrationTargetChannel[];
  value: string | null;
  editing: boolean;
  onChange: (targetChannelId: string | null) => void;
}) {
  const options = [
    ...compatibleTargets.map((t) => ({ label: t.name, value: t.id })),
    { label: 'Skip this channel', value: SKIP_VALUE },
  ];

  return (
    <div className="flex flex-col gap-1.5 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
      <div className="min-w-0">
        <ClampedText text={channel.name} lines={1} className="text-sm font-medium" />
        <ClampedText text={channel.source} lines={1} className="text-muted-foreground text-xs" />
      </div>
      <div className="w-full sm:max-w-xs">
        <SearchSelect
          ariaLabel={`Target channel for ${channel.name}`}
          options={options}
          value={value ?? SKIP_VALUE}
          disabled={!editing}
          onChange={(next) => onChange(next === SKIP_VALUE ? null : next)}
        />
      </div>
    </div>
  );
}
