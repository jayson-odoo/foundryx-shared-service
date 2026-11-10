'use client';

import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { SearchSelect } from '@/components/platform/search-select';
import { ClampedText } from '@/components/platform/clamped-text';
import { channelsListPath } from '@/app/(protected)/omnichannel/settings/channels/components/paths';
import type { MigrationSourceChannel, MigrationTargetChannel } from '@/types/respondio-migration';

const SKIP_VALUE = '__skip__';

/**
 * One Channels-section row (AC-MIG-04): a source channel maps to a target
 * channel whose `channelType` is compatible with the source's respond.io
 * `source` value, or "Skip for now". A source with zero compatible targets
 * renders with ONLY the Skip option - the picker never offers a target that
 * would silently misroute a channel's history - plus "No channel connected"
 * and a Connect channel link (lane SS-CHANNEL-SKIP): contacts and history
 * still import, and a later re-run with the channel mapped links them.
 * The link opens a new tab so the unsaved setup form survives.
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
    { label: 'Skip for now', value: SKIP_VALUE },
  ];
  const noTarget = compatibleTargets.length === 0;

  return (
    <div className="flex flex-col gap-1.5 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
      <div className="min-w-0">
        <ClampedText text={channel.name} lines={1} className="text-sm font-medium" />
        <ClampedText text={channel.source} lines={1} className="text-muted-foreground text-xs" />
        {noTarget && (
          <div className="flex flex-wrap items-center gap-x-2 text-xs">
            <span className="text-muted-foreground">No channel connected</span>
            <Button mode="link" underlined="dashed" size="sm" asChild>
              <Link href={channelsListPath} target="_blank" rel="noopener noreferrer">
                Connect channel
              </Link>
            </Button>
          </div>
        )}
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

/**
 * A source channel the server could not read: only the vendor id is known, so
 * the sole choice is "Skip this channel". Nothing shows as chosen until the
 * operator picks it, and no map entry exists before then.
 */
export function UnreadableChannelRow({
  sourceChannelId,
  skipped,
  editing,
  onSkip,
}: {
  sourceChannelId: string;
  skipped: boolean;
  editing: boolean;
  onSkip: () => void;
}) {
  return (
    <div className="flex flex-col gap-1.5 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
      <div className="min-w-0">
        <ClampedText text={sourceChannelId} lines={1} className="text-sm font-medium" />
        <p className="text-muted-foreground text-xs">Could not be read</p>
      </div>
      <div className="w-full sm:max-w-xs">
        <SearchSelect
          ariaLabel={`Skip channel ${sourceChannelId}`}
          options={[{ label: 'Skip this channel', value: SKIP_VALUE }]}
          value={skipped ? SKIP_VALUE : null}
          disabled={!editing}
          onChange={onSkip}
        />
      </div>
    </div>
  );
}
