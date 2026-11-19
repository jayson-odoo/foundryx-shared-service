'use client';

/**
 * "Connect a service" with the Foundryx UIUX switch on (gap audit 12, owner
 * answer "Connect on each card"): one card per channel type with its logo,
 * its name, a chip for how many are connected (neutral "Not connected" when
 * none) and its own Connect button, which opens the connect wizard with that
 * type already picked. The page has no red action of its own; each card's
 * button is local.
 */
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { CHANNEL_CAPABILITIES, CHANNEL_TYPES } from '@/lib/channel-capabilities';
import type { ChannelType } from '@/types/omnichannel';
import type { ChannelTypeCounts } from './use-channel-type-counts';

export function FxConnectServices({
  counts,
  canConnect,
  onConnect,
}: {
  counts: ChannelTypeCounts;
  canConnect: boolean;
  onConnect: (type: ChannelType) => void;
}) {
  return (
    <section aria-label="Connect a service" className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {CHANNEL_TYPES.map((type) => {
        const caps = CHANNEL_CAPABILITIES[type];
        const Icon = caps.icon;
        const n = counts?.[type];
        return (
          <div
            key={type}
            data-fx-service={type}
            className="flex items-center gap-3 rounded-(--fx-r-l) border border-(--fx-line) bg-(--fx-surface) p-4 text-(--fx-ink)"
          >
            <span
              className={cn('flex size-10 shrink-0 items-center justify-center rounded-(--fx-r-m)', caps.accentClassName)}
            >
              <Icon aria-hidden="true" className="size-5" />
            </span>
            <div className="flex min-w-0 flex-1 flex-col items-start gap-1">
              <span className="font-semibold leading-tight">{caps.label}</span>
              {n !== undefined && (
                <span
                  className={cn(
                    'inline-flex h-5 items-center rounded-(--fx-r-pill) px-2 text-xs font-semibold',
                    n > 0 ? 'bg-(--fx-ok-bg) text-(--fx-ok-ink)' : 'bg-(--fx-chip) text-(--fx-chip-ink)',
                  )}
                >
                  {n > 0 ? `${n} connected` : 'Not connected'}
                </span>
              )}
            </div>
            {canConnect && (
              <Button
                type="button"
                variant="fx-quiet"
                className="h-auto min-h-9 shrink-0 px-4 text-(--fx-ink)"
                aria-label={`Connect ${caps.label}`}
                onClick={() => onConnect(type)}
              >
                Connect
              </Button>
            )}
          </div>
        );
      })}
    </section>
  );
}
