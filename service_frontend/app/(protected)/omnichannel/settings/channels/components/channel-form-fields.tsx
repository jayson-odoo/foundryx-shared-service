'use client';

import type { UseFormReturn } from 'react-hook-form';
import Link from 'next/link';
import { toast } from '@/lib/toast';
import { useState } from 'react';
import { PlugZap, Loader2, RefreshCw } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { FormControl, FormField, FormItem, FormMessage } from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { Skeleton } from '@/components/ui/skeleton';
import { FormRow } from '@/components/platform/resource-form';
import { StatusBadge } from '@/components/platform/status-badge';
import { ClampedText } from '@/components/platform/clamped-text';
import { OriginsEditor } from '@/app/(protected)/omnichannel/settings/embed/origins-editor';
import { channelService } from '@/services/channel-service';
import { useDatetime } from '@/hooks/use-datetime';
import { useCan } from '@/hooks/use-can';
import { useWebchatConfig } from '@/hooks/use-webchat-config';
import type { Channel } from '@/types/omnichannel';
import { workspaceFormPath } from '../../workspaces/components/paths';
import { CHANNEL_STATUS_REGISTRY, CHANNEL_TYPE_LABELS } from './channel-status';
import type { ChannelDetailValues } from './channel-schema';

export interface ConfigurationTabProps {
  form: UseFormReturn<ChannelDetailValues>;
  editing: boolean;
  channel: Channel | null;
  channelId: string;
  /** Refresh the parent's channel state after a Sync / Test stamps new data. */
  onChannelSynced: (channel: Channel) => void;
}

/**
 * Widget key + allowed-origins block for a `WEBCHAT` channel (plan 34 / A7b,
 * AC-WEB-03) - replaces the Meta-owned identity block. Self-contained: its
 * OWN `useWebchatConfig` read + the origins editor's OWN self-save (the same
 * component the embed settings screen uses, unmodified in this mode), so it
 * works regardless of the record's global Edit toggle - there is nothing
 * Meta-synced to gate here.
 */
function WebchatIdentityBlock({ channelId }: { channelId: string }) {
  const { config, isLoading, save } = useWebchatConfig(channelId, true);

  if (isLoading) {
    return (
      <FormRow label="Widget key">
        <Skeleton className="h-4 w-48" />
      </FormRow>
    );
  }

  return (
    <>
      <FormRow label="Widget key">
        <SyncedValue value={config?.widgetKey} mono />
      </FormRow>
      {config && (
        <FormRow label="Allowed origins">
          <OriginsEditor
            origins={config.allowedOrigins}
            onSave={(origins) => save({ allowedOrigins: origins }).then(() => undefined)}
            bare
          />
        </FormRow>
      )}
    </>
  );
}

/** Read-only synced value with a monospace option + ClampedText for long text. */
function SyncedValue({ value, mono }: { value: string | null | undefined; mono?: boolean }) {
  if (!value) return <span className="text-muted-foreground">-</span>;
  if (mono) return <span className="font-mono text-xs">{value}</span>;
  return <ClampedText text={value} lines={1} />;
}

/**
 * Configuration tab - merges the old General + Connection tabs. Editable: name,
 * workspace (link), active. Read-only synced (Meta-owned) identity block with a
 * "last synced" caption, plus Sync + Test Connection actions.
 */
export function ConfigurationTab({ form, editing, channel, channelId, onChannelSynced }: ConfigurationTabProps) {
  const { formatDate, formatDateTime } = useDatetime();
  const { can } = useCan();
  const canManage = can('channels.manage');
  const [syncing, setSyncing] = useState(false);
  const [testing, setTesting] = useState(false);

  const runSync = async () => {
    if (!channel) return;
    setSyncing(true);
    try {
      const updated = await channelService.syncConfig(channel.id);
      onChannelSynced(updated);
      toast.success('Configuration synced from Meta.');
    } catch {
      toast.error('Could not sync configuration. Please try again.');
    } finally {
      setSyncing(false);
    }
  };

  const runTest = async () => {
    if (!channel) return;
    setTesting(true);
    try {
      const res = await channelService.testConnection(channel.id);
      if (res.ok) {
        toast.success(res.message);
        onChannelSynced({ ...channel, lastVerifiedAt: res.checkedAt });
      } else {
        toast.error(res.message);
      }
    } catch {
      toast.error('Connection test failed. Please try again.');
    } finally {
      setTesting(false);
    }
  };

  const lastSynced = channel?.lastVerifiedAt
    ? `Last synced ${formatDateTime(channel.lastVerifiedAt)}`
    : 'Never synced';

  return (
    <Card>
      <CardContent className="py-1">
        {/* ── Our data (editable) ── */}
        <FormRow label="Channel name" required={editing}>
          {editing ? (
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem className="max-w-sm">
                  <FormControl>
                    <Input placeholder="Channel name" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          ) : (
            (channel?.name ?? '-')
          )}
        </FormRow>

        <FormRow label="Channel type">
          {channel ? CHANNEL_TYPE_LABELS[channel.channelType] : '-'}
        </FormRow>

        <FormRow label="Workspace">
          {channel ? (
            <Link
              href={workspaceFormPath(channel.workspaceId)}
              className="text-primary hover:underline"
            >
              {channel.workspaceName}
            </Link>
          ) : (
            '-'
          )}
        </FormRow>

        <FormRow label="Status">
          <StatusBadge status={channel?.status ?? 'INACTIVE'} registry={CHANNEL_STATUS_REGISTRY} />
        </FormRow>

        <FormRow label="Active">
          {editing ? (
            <FormField
              control={form.control}
              name="isActive"
              render={({ field }) => (
                <FormItem>
                  <FormControl>
                    <Switch checked={field.value} onCheckedChange={field.onChange} />
                  </FormControl>
                </FormItem>
              )}
            />
          ) : (
            <Switch checked={channel?.isActive ?? false} disabled />
          )}
        </FormRow>

        <FormRow label="Connected">{channel ? formatDate(channel.createdAt) : '-'}</FormRow>

        {/* ── Provider-owned identity (synced, read-only even in Edit) ── */}
        {channel?.channelType === 'WHATSAPP' ? (
          <>
            <FormRow label="Display number">
              <SyncedValue value={channel?.displayPhoneNumber} />
            </FormRow>
            <FormRow label="Verified name">
              <SyncedValue value={channel?.verifiedName} />
            </FormRow>
            <FormRow label="Business account">
              <SyncedValue value={channel?.businessAccountName} />
            </FormRow>
            <FormRow label="Phone number ID">
              <SyncedValue value={channel?.phoneNumberId} mono />
            </FormRow>
            <FormRow label="WABA ID">
              <SyncedValue value={channel?.wabaId} mono />
            </FormRow>
          </>
        ) : channel?.channelType === 'WEBCHAT' ? (
          // Plan 34 / A7b, AC-WEB-03 - the widget key + the origins editor
          // (self-save, unmodified, D-A7B-13) replace the Meta identity block
          // entirely: web chat has no external provider to mirror.
          <WebchatIdentityBlock channelId={channelId} />
        ) : (
          // Messenger/Instagram identity block (plan 32 / A7a, AC-CHN-05) -
          // the Page (or its linked Instagram account) is the routing key,
          // the equivalent of `phoneNumberId` for these channel types.
          <>
            <FormRow label={channel?.channelType === 'INSTAGRAM' ? 'Instagram account' : 'Facebook Page'}>
              <SyncedValue value={channel?.externalAccountName} />
            </FormRow>
            <FormRow label={channel?.channelType === 'INSTAGRAM' ? 'Account ID' : 'Page ID'}>
              <SyncedValue value={channel?.externalAccountId} mono />
            </FormRow>
          </>
        )}

        {channel?.channelType !== 'WEBCHAT' && (
          <FormRow label="Identity">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <span className="text-xs text-muted-foreground">{lastSynced}</span>
              {canManage && (
                <div className="flex flex-wrap gap-2">
                  <Button variant="outline" size="sm" onClick={runSync} disabled={syncing || !channel}>
                    {syncing ? (
                      <Loader2 className="size-4 animate-spin" />
                    ) : (
                      <RefreshCw className="size-4" />
                    )}
                    {syncing ? 'Syncing…' : 'Sync'}
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={runTest}
                    disabled={testing || !channel}
                  >
                    {testing ? (
                      <Loader2 className="size-4 animate-spin" />
                    ) : (
                      <PlugZap className="size-4" />
                    )}
                    {testing ? 'Testing…' : 'Test connection'}
                  </Button>
                </div>
              )}
            </div>
          </FormRow>
        )}
      </CardContent>
    </Card>
  );
}
