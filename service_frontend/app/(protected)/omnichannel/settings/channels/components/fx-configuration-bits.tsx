'use client';

/**
 * The Configuration tab's status and identity rows with the Foundryx UIUX
 * switch on (gap audit 12): the status chip with its reason in plain words,
 * and Sync / Test connection with the test result beside the buttons
 * instead of a toast. Same requests as the legacy rows.
 */
import { useFxActor } from './use-fx-actor';
import { useState } from 'react';
import { Loader2, PlugZap, RefreshCw } from 'lucide-react';
import { toast } from '@/lib/toast';
import { Button } from '@/components/ui/button';
import { channelService } from '@/services/channel-service';
import { useDatetime } from '@/hooks/use-datetime';
import type { Channel } from '@/types/omnichannel';
import { FxChannelChip, FxTestResultLine, channelErrorReason } from './fx-channel-card';
import { fxTestConnection } from './use-channel-actions';

export function FxStatusRow({ channel }: { channel: Channel | null }) {
  return (
    <div className="flex flex-col items-start gap-1">
      <FxChannelChip status={channel?.status ?? 'INACTIVE'} />
      {channel?.status === 'ERROR' && <span className="text-sm text-(--fx-warn-ink)">{channelErrorReason(channel)}</span>}
    </div>
  );
}

export function FxIdentityRow({
  channel,
  canManage,
  onChannelSynced,
}: {
  channel: Channel | null;
  canManage: boolean;
  onChannelSynced: (channel: Channel) => void;
}) {
  const { formatDateTime } = useDatetime();
  const byWhom = useFxActor();
  const [syncing, setSyncing] = useState(false);
  const [testing, setTesting] = useState(false);
  const [syncFailed, setSyncFailed] = useState(false);

  const runSync = async () => {
    if (!channel || syncing) return;
    setSyncing(true);
    setSyncFailed(false);
    try {
      const updated = await channelService.syncConfig(channel.id);
      onChannelSynced(updated);
      toast.fxDone({
        what: `${updated.name} synced from Meta`,
        byWhom: byWhom,
      });
    } catch {
      setSyncFailed(true);
    } finally {
      setSyncing(false);
    }
  };

  const runTest = async () => {
    if (!channel || testing) return;
    setTesting(true);
    try {
      const res = await fxTestConnection(channel);
      if (res?.ok) onChannelSynced({ ...channel, lastVerifiedAt: res.checkedAt });
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="flex flex-col gap-2">
      <span className="text-sm text-(--fx-ink-2)">
        {channel?.lastVerifiedAt ? `Last checked ${formatDateTime(channel.lastVerifiedAt)}` : 'Not checked yet'}
      </span>
      {canManage && (
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="fx-quiet"
            className="h-auto min-h-9 px-4 text-(--fx-ink)"
            onClick={runSync}
            aria-disabled={syncing || !channel ? true : undefined}
          >
            {syncing ? <Loader2 aria-hidden="true" className="size-4 animate-spin" /> : <RefreshCw aria-hidden="true" className="size-4" />}
            Sync from Meta
          </Button>
          <Button
            type="button"
            variant="fx-quiet"
            className="h-auto min-h-9 px-4 text-(--fx-ink)"
            onClick={runTest}
            aria-disabled={testing || !channel ? true : undefined}
          >
            {testing ? <Loader2 aria-hidden="true" className="size-4 animate-spin" /> : <PlugZap aria-hidden="true" className="size-4" />}
            Test connection
          </Button>
        </div>
      )}
      {syncFailed && (
        <p role="alert" className="text-sm font-semibold text-[color-mix(in_srgb,var(--fx-act)_82%,var(--fx-surface))]">
          Couldn&apos;t sync from Meta. Try again.
        </p>
      )}
      {channel && <FxTestResultLine channelId={channel.id} />}
    </div>
  );
}
