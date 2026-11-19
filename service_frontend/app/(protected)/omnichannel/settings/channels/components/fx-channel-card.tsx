'use client';

/**
 * A connected service's card with the Foundryx UIUX switch on (gap audit 12,
 * "Connected services"): its logo, its name, the account it is connected to,
 * its state as a status chip and when it was last checked.
 * - Needs attention (Error): the reason in plain words and Reconnect as the
 *   card's one button (WhatsApp: the existing Replace token dialog, the same
 *   request).
 * - Test connection (the card's More menu): its result shows on the card.
 */
import { Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { useDatetime } from '@/hooks/use-datetime';
import { channelCapabilities } from '@/lib/channel-capabilities';
import type { Channel, ChannelStatus } from '@/types/omnichannel';
import { CHANNEL_STATUS_REGISTRY, CHANNEL_TYPE_LABELS } from './channel-status';
import { useChannelTestResult } from './channel-test-results';

const CHIP: Record<ChannelStatus, string> = {
  ACTIVE: 'bg-(--fx-ok-bg) text-(--fx-ok-ink)',
  PENDING: 'bg-(--fx-warn-bg) text-(--fx-warn-ink)',
  INACTIVE: 'bg-(--fx-chip) text-(--fx-chip-ink)',
  ERROR: 'bg-(--fx-warn-bg) text-(--fx-warn-ink)',
};

/** The playbook's status chip for a channel's connection state. */
export function FxChannelChip({ status, className }: { status: ChannelStatus; className?: string }) {
  return (
    <span
      className={cn(
        'inline-flex h-6 items-center rounded-(--fx-r-pill) px-2.5 text-xs font-semibold',
        CHIP[status],
        className,
      )}
    >
      {status === 'ERROR' ? 'Needs attention' : CHANNEL_STATUS_REGISTRY[status].label}
    </span>
  );
}

/** "Maju Sales · +60 3-7890 1200": the account a channel is connected to. */
export function channelAccountLine(c: Channel): string {
  if (c.channelType === 'WHATSAPP') {
    return [c.verifiedName ?? c.businessAccountName, c.displayPhoneNumber].filter(Boolean).join(' · ');
  }
  if (c.channelType === 'WEBCHAT') return c.workspaceName;
  return c.externalAccountName ?? '';
}

/** What an Error channel says, in plain words. */
export function channelErrorReason(c: Channel): string {
  return c.channelType === 'WHATSAPP'
    ? 'Access expired or was revoked. Reconnect to keep receiving messages.'
    : 'Access expired or was revoked. New messages may not arrive.';
}

/** The last Test connection result, beside the channel. */
export function FxTestResultLine({ channelId, className }: { channelId: string; className?: string }) {
  const result = useChannelTestResult(channelId);
  const { formatTime } = useDatetime();
  if (!result) return null;
  if (result === 'testing') {
    return (
      <p role="status" className={cn('flex items-center gap-1.5 text-sm text-(--fx-ink-2)', className)}>
        <Loader2 aria-hidden="true" className="size-3.5 animate-spin" />
        Testing the connection
      </p>
    );
  }
  return (
    <p
      role={result.ok ? 'status' : 'alert'}
      className={cn(
        'text-sm',
        result.ok
          ? 'text-(--fx-ok-ink)'
          : 'font-semibold text-[color-mix(in_srgb,var(--fx-act)_82%,var(--fx-surface))]',
        className,
      )}
    >
      {result.ok ? `Connection works. Checked ${formatTime(result.checkedAt)}.` : result.message}
    </p>
  );
}

export function FxChannelCard({
  channel,
  canReconnect,
  onReconnect,
}: {
  channel: Channel;
  canReconnect: boolean;
  onReconnect: (channel: Channel) => void;
}) {
  const { formatRelative, formatDateTime } = useDatetime();
  const caps = channelCapabilities(channel.channelType);
  const Icon = caps.icon;
  const account = channelAccountLine(channel);
  const needsAttention = channel.status === 'ERROR' && !channel.isTrashed;
  const reconnect = needsAttention && canReconnect && channel.channelType === 'WHATSAPP';

  return (
    <div className="flex flex-col gap-3" data-fx-channel-card={channel.id}>
      <div className="flex items-center gap-3 pe-6">
        <span className={cn('flex size-10 shrink-0 items-center justify-center rounded-(--fx-r-m)', caps.accentClassName)}>
          <Icon aria-hidden="true" className="size-5" />
        </span>
        <div className="flex min-w-0 flex-col">
          <span className="font-semibold leading-tight text-(--fx-ink) [overflow-wrap:anywhere]">{channel.name}</span>
          <span className="text-sm text-(--fx-ink-3)">{CHANNEL_TYPE_LABELS[channel.channelType]}</span>
        </div>
      </div>
      {account && <p className="text-sm text-(--fx-ink-2) [overflow-wrap:anywhere]">{account}</p>}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <FxChannelChip status={channel.status} />
        {channel.lastVerifiedAt && (
          <span className="text-sm text-(--fx-ink-3)" title={formatDateTime(channel.lastVerifiedAt)}>
            Last checked {formatRelative(channel.lastVerifiedAt)}
          </span>
        )}
      </div>
      {needsAttention && <p className="text-sm text-(--fx-warn-ink)">{channelErrorReason(channel)}</p>}
      <FxTestResultLine channelId={channel.id} />
      {reconnect && (
        <div
          role="presentation"
          className="flex"
          onClick={(e) => e.stopPropagation()}
          onKeyDown={(e) => e.stopPropagation()}
        >
          <Button
            type="button"
            variant="fx-quiet"
            className="h-auto min-h-9 px-4 text-(--fx-ink)"
            onClick={() => onReconnect(channel)}
          >
            Reconnect
          </Button>
        </div>
      )}
    </div>
  );
}
