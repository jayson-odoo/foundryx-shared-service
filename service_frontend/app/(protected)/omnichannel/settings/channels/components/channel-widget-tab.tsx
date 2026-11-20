'use client';

import { useState } from 'react';
import type { UseFormReturn } from 'react-hook-form';
import { KeyRound } from 'lucide-react';
import { toast } from '@/lib/toast';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { FormControl, FormField, FormItem, FormMessage } from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import { FormRow } from '@/components/platform/resource-form';
import { SearchSelect } from '@/components/platform/search-select';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import { CopyField } from '@/app/(protected)/omnichannel/settings/embed/copy-field';
import { SnippetCard } from '@/app/(protected)/omnichannel/settings/embed/snippet-card';
import { useWebchatConfig } from '@/hooks/use-webchat-config';
import type { ResourceAction } from '@/components/platform/resource-list';
import type { WebchatConfig } from '@/types/omnichannel';
import type { ChannelDetailValues } from './channel-schema';

export interface ChannelWidgetTabProps {
  form: UseFormReturn<ChannelDetailValues>;
  editing: boolean;
  channelId: string;
  /** Loaded by `use-channel-form.tsx` alongside the channel/profile fetch, so
   *  the Widget tab's fields join the SAME single-Save form as every other
   *  tab (D-A7-17's "one form, one edit toggle" convention). */
  webchatConfig: WebchatConfig | null;
}

const POSITION_OPTIONS = [
  { value: 'left', label: 'Left' },
  { value: 'right', label: 'Right' },
];

/** A minimal `ResourceAction` array for the tab-local "Rotate widget secret"
 *  action - not the record's row/bulk registry, just a standalone dots menu
 *  scoped to this one action (AC-WEB-06). */
function rotateSecretAction(run: () => void): ResourceAction<{ id: string }>[] {
  return [
    {
      id: 'rotate-widget-secret',
      label: 'Rotate widget secret',
      icon: KeyRound,
      permission: 'channels.manage',
      surfaces: { form: true },
      run: () => run(),
    },
  ];
}

/**
 * Widget tab (plan 34 / A7b, AC-WEB-04/05/06) - appearance, greetings,
 * pre-chat toggles and the install snippet for a `WEBCHAT` channel. Fields
 * join the shared record form (read by default, the global Edit toggle
 * reveals inputs, Save persists through `use-channel-form.tsx`'s widget PATCH
 * branch); the install snippet and the secret-rotate action are standalone
 * (nothing to "edit" about a server-generated string).
 */
export function ChannelWidgetTab({ form, editing, channelId, webchatConfig }: ChannelWidgetTabProps) {
  // `enabled: false` - the config READ already comes from the parent (single
  // fetch, shared with the mega-form); this only borrows the hook's imperative
  // `rotateSecret` (which needs nothing but the channel id) without a second
  // GET firing alongside the parent's.
  const { rotateSecret } = useWebchatConfig(channelId, false);
  const [rotating, setRotating] = useState(false);
  const [rotatedSecret, setRotatedSecret] = useState<string | null>(null);

  const runRotate = async () => {
    setRotating(true);
    try {
      const secret = await rotateSecret();
      setRotatedSecret(secret);
    } catch {
      toast.error('Could not rotate the widget secret. Please try again.');
    } finally {
      setRotating(false);
    }
  };

  if (!webchatConfig) {
    return (
      <Card>
        <CardContent className="flex flex-col gap-3 py-4">
          <Skeleton className="h-4 w-1/3" />
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="h-4 w-1/2" />
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardContent className="py-1">
          <FormRow label="Accent color">
            {editing ? (
              <FormField
                control={form.control}
                name="widgetAccentColor"
                render={({ field }) => (
                  <FormItem className="max-w-40">
                    <div className="flex items-center gap-2">
                      <label
                        className="relative size-7 shrink-0 rounded-md border border-input"
                        style={{ backgroundColor: field.value }}
                      >
                        <input
                          type="color"
                          className="absolute inset-0 size-full cursor-pointer opacity-0"
                          value={field.value ?? '#FF5A00'}
                          aria-label="Accent color"
                          onChange={(e) => field.onChange(e.target.value)}
                        />
                      </label>
                      <FormControl>
                        <Input className="font-mono text-xs uppercase" {...field} />
                      </FormControl>
                    </div>
                    <FormMessage />
                  </FormItem>
                )}
              />
            ) : (
              <div className="flex items-center gap-2">
                <span
                  className="size-4 rounded-full border border-input"
                  style={{ backgroundColor: webchatConfig.appearance.accentColor }}
                />
                {webchatConfig.appearance.accentColor}
              </div>
            )}
          </FormRow>

          <FormRow label="Launcher position">
            {editing ? (
              <FormField
                control={form.control}
                name="widgetPosition"
                render={({ field }) => (
                  <FormItem className="max-w-40">
                    <FormControl>
                      <SearchSelect
                        options={POSITION_OPTIONS}
                        value={field.value ?? 'right'}
                        onChange={field.onChange}
                        ariaLabel="Launcher position"
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            ) : (
              POSITION_OPTIONS.find((o) => o.value === webchatConfig.appearance.position)?.label
            )}
          </FormRow>

          <FormRow label="Header title">
            {editing ? (
              <FormField
                control={form.control}
                name="widgetHeaderTitle"
                render={({ field }) => (
                  <FormItem className="max-w-sm">
                    <FormControl>
                      <Input {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            ) : (
              webchatConfig.appearance.headerTitle
            )}
          </FormRow>

          <FormRow label="Agent display name">
            {editing ? (
              <FormField
                control={form.control}
                name="widgetAgentDisplayName"
                render={({ field }) => (
                  <FormItem className="max-w-sm">
                    <FormControl>
                      <Input {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            ) : (
              webchatConfig.appearance.agentDisplayName
            )}
          </FormRow>

          <FormRow label="Greeting">
            {editing ? (
              <FormField
                control={form.control}
                name="widgetGreeting"
                render={({ field }) => (
                  <FormItem className="max-w-lg">
                    <FormControl>
                      <Textarea rows={2} {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            ) : (
              webchatConfig.greeting
            )}
          </FormRow>

          <FormRow label="Offline greeting">
            {editing ? (
              <FormField
                control={form.control}
                name="widgetOfflineGreeting"
                render={({ field }) => (
                  <FormItem className="max-w-lg">
                    <FormControl>
                      <Textarea rows={2} {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            ) : (
              webchatConfig.offlineGreeting
            )}
          </FormRow>

          <FormRow label="Ask for name">
            {editing ? (
              <FormField
                control={form.control}
                name="widgetAskName"
                render={({ field }) => (
                  <FormItem>
                    <FormControl>
                      <Switch checked={field.value ?? false} onCheckedChange={field.onChange} />
                    </FormControl>
                  </FormItem>
                )}
              />
            ) : (
              <Switch checked={webchatConfig.preChat.askName} disabled />
            )}
          </FormRow>

          <FormRow label="Ask for email">
            {editing ? (
              <FormField
                control={form.control}
                name="widgetAskEmail"
                render={({ field }) => (
                  <FormItem>
                    <FormControl>
                      <Switch checked={field.value ?? false} onCheckedChange={field.onChange} />
                    </FormControl>
                  </FormItem>
                )}
              />
            ) : (
              <Switch checked={webchatConfig.preChat.askEmail} disabled />
            )}
          </FormRow>

          <FormRow label="Ask for phone">
            {editing ? (
              <FormField
                control={form.control}
                name="widgetAskPhone"
                render={({ field }) => (
                  <FormItem>
                    <FormControl>
                      <Switch checked={field.value ?? false} onCheckedChange={field.onChange} />
                    </FormControl>
                  </FormItem>
                )}
              />
            ) : (
              <Switch checked={webchatConfig.preChat.askPhone} disabled />
            )}
          </FormRow>
        </CardContent>
      </Card>

      <SnippetCard
        mode="raw"
        title="Install snippet"
        description="Paste this into the page that hosts the widget."
        snippet={webchatConfig.snippet}
      />

      <Card>
        <CardContent className="flex items-center justify-between gap-2 py-4">
          <div className="flex flex-col">
            <span className="text-sm font-medium text-foreground">Widget secret</span>
            <span className="text-xs text-muted-foreground">
              Signs host identity assertions. Not shown after connect.
            </span>
          </div>
          <ActionMenu
            actions={rotateSecretAction(() => void runRotate())}
            rows={[{ id: channelId }]}
            runtime={{ reload: () => undefined }}
            surface="form"
          />
        </CardContent>
      </Card>

      <Dialog open={!!rotatedSecret} onOpenChange={(o) => !o && setRotatedSecret(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Widget secret rotated</DialogTitle>
          </DialogHeader>
          <DialogBody className="flex flex-col gap-3">
            {rotatedSecret && <CopyField value={rotatedSecret} ariaLabel="Widget secret" />}
            <p className="text-sm font-medium text-destructive">
              Copy this secret now - it won&apos;t be shown again.
            </p>
          </DialogBody>
          <DialogFooter>
            <Button onClick={() => setRotatedSecret(null)} disabled={rotating}>
              Done
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
