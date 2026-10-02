'use client';

import type { UseFormReturn } from 'react-hook-form';
import { useState } from 'react';
import { toast } from '@/lib/toast';
import { Loader2, RefreshCw } from 'lucide-react';
import Image from 'next/image';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { FormControl, FormField, FormItem, FormMessage } from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { FormRow } from '@/components/platform/resource-form';
import { SearchSelect } from '@/components/platform/search-select';
import { ClampedText } from '@/components/platform/clamped-text';
import { channelService } from '@/services/channel-service';
import { useDatetime } from '@/hooks/use-datetime';
import { useCan } from '@/hooks/use-can';
import { WHATSAPP_VERTICAL_LABELS, WHATSAPP_VERTICAL_OPTIONS } from '@/lib/whatsapp-verticals';
import type { Channel, ChannelProfile } from '@/types/omnichannel';
import type { ChannelDetailValues } from './channel-schema';

export interface ChannelProfileTabProps {
  form: UseFormReturn<ChannelDetailValues>;
  editing: boolean;
  channel: Channel | null;
  profile: ChannelProfile | null;
  /** Refresh parent state after Sync Profile overwrites the local mirror. */
  onProfileSynced: (profile: ChannelProfile) => void;
}

function ReadValue({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="text-muted-foreground">-</span>;
  return <ClampedText text={value} lines={2} />;
}

/**
 * Profile tab - the mirrored WhatsApp Business Profile (write-through). Read by
 * default; the shell's global Edit toggle reveals the inputs. Sync Profile pulls
 * from Meta; Save is the form's global Save (handled in use-channel-form).
 */
export function ChannelProfileTab({
  form,
  editing,
  channel,
  profile,
  onProfileSynced,
}: ChannelProfileTabProps) {
  const { formatDateTime } = useDatetime();
  const { can } = useCan();
  const canManage = can('channels.manage');
  const [syncing, setSyncing] = useState(false);

  const runSyncProfile = async () => {
    if (!channel) return;
    setSyncing(true);
    try {
      const synced = await channelService.syncProfile(channel.id);
      onProfileSynced(synced);
      toast.success('Profile synced from Meta.');
    } catch {
      toast.error('Could not sync the profile. Please try again.');
    } finally {
      setSyncing(false);
    }
  };

  const lastSynced = profile?.profileSyncedAt
    ? `Last synced ${formatDateTime(profile.profileSyncedAt)}`
    : 'Never synced';

  return (
    <Card>
      <CardContent className="py-1">
        <FormRow label="About">
          {editing ? (
            <FormField
              control={form.control}
              name="about"
              render={({ field }) => (
                <FormItem className="max-w-lg">
                  <FormControl>
                    <Textarea rows={2} placeholder="A short tagline" {...field} value={field.value ?? ''} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          ) : (
            <ReadValue value={profile?.about} />
          )}
        </FormRow>

        <FormRow label="Description">
          {editing ? (
            <FormField
              control={form.control}
              name="description"
              render={({ field }) => (
                <FormItem className="max-w-lg">
                  <FormControl>
                    <Textarea rows={3} placeholder="What your business does" {...field} value={field.value ?? ''} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          ) : (
            <ReadValue value={profile?.description} />
          )}
        </FormRow>

        <FormRow label="Address">
          {editing ? (
            <FormField
              control={form.control}
              name="address"
              render={({ field }) => (
                <FormItem className="max-w-lg">
                  <FormControl>
                    <Input placeholder="Business address" {...field} value={field.value ?? ''} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          ) : (
            <ReadValue value={profile?.address} />
          )}
        </FormRow>

        <FormRow label="Email">
          {editing ? (
            <FormField
              control={form.control}
              name="email"
              render={({ field }) => (
                <FormItem className="max-w-sm">
                  <FormControl>
                    <Input type="email" placeholder="contact@business.com" {...field} value={field.value ?? ''} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          ) : (
            <ReadValue value={profile?.email} />
          )}
        </FormRow>

        <FormRow label="Vertical">
          {editing ? (
            <FormField
              control={form.control}
              name="vertical"
              render={({ field }) => (
                <FormItem className="max-w-sm">
                  <FormControl>
                    <SearchSelect
                      options={WHATSAPP_VERTICAL_OPTIONS}
                      value={field.value ?? ''}
                      onChange={field.onChange}
                      ariaLabel="Business vertical"
                      placeholder="Select a vertical"
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          ) : (
            <ReadValue
              value={profile?.vertical ? WHATSAPP_VERTICAL_LABELS[profile.vertical as never] ?? profile.vertical : null}
            />
          )}
        </FormRow>

        <FormRow label="Website 1">
          {editing ? (
            <FormField
              control={form.control}
              name="website1"
              render={({ field }) => (
                <FormItem className="max-w-sm">
                  <FormControl>
                    <Input placeholder="https://example.com" {...field} value={field.value ?? ''} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          ) : (
            <ReadValue value={profile?.website1} />
          )}
        </FormRow>

        <FormRow label="Website 2">
          {editing ? (
            <FormField
              control={form.control}
              name="website2"
              render={({ field }) => (
                <FormItem className="max-w-sm">
                  <FormControl>
                    <Input placeholder="https://example.com" {...field} value={field.value ?? ''} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          ) : (
            <ReadValue value={profile?.website2} />
          )}
        </FormRow>

        <FormRow label="Profile photo">
          {profile?.profilePictureUrl ? (
            <Image
              src={profile.profilePictureUrl}
              alt="Profile photo"
              width={64}
              height={64}
              className="size-16 rounded-md object-cover"
              unoptimized
            />
          ) : (
            <span className="text-muted-foreground">No photo set</span>
          )}
        </FormRow>

        <FormRow label="Mirror">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <span className="text-xs text-muted-foreground">{lastSynced}</span>
            {canManage && (
              <Button
                variant="outline"
                size="sm"
                onClick={runSyncProfile}
                disabled={syncing || !channel}
              >
                {syncing ? <Loader2 className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
                {syncing ? 'Syncing…' : 'Sync profile'}
              </Button>
            )}
          </div>
        </FormRow>
      </CardContent>
    </Card>
  );
}
