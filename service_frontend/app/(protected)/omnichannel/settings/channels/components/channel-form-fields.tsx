'use client';

import type { UseFormReturn } from 'react-hook-form';
import Link from 'next/link';
import { toast } from 'sonner';
import { useState } from 'react';
import { PlugZap, Loader2, RefreshCw } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { FormControl, FormField, FormItem, FormMessage } from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { FormRow } from '@/components/platform/resource-form';
import { StatusBadge } from '@/components/platform/status-badge';
import { ClampedText } from '@/components/platform/clamped-text';
import { channelService } from '@/services/channel-service';
import { useDatetime } from '@/hooks/use-datetime';
import { useCan } from '@/hooks/use-can';
import type { Channel } from '@/types/omnichannel';
import { workspaceFormPath } from '../../workspaces/components/paths';
import { CHANNEL_STATUS_REGISTRY, CHANNEL_TYPE_LABELS } from './channel-status';
import type { ChannelDetailValues } from './channel-schema';

export interface ConfigurationTabProps {
  form: UseFormReturn<ChannelDetailValues>;
  editing: boolean;
  channel: Channel | null;
  /** Refresh the parent's channel state after a Sync / Test stamps new data. */
  onChannelSynced: (channel: Channel) => void;
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
export function ConfigurationTab({ form, editing, channel, onChannelSynced }: ConfigurationTabProps) {
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

        {/* ── Meta-owned identity (synced, read-only even in Edit) ── */}
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
      </CardContent>
    </Card>
  );
}
