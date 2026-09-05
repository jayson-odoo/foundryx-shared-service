'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { zodResolver } from '@hookform/resolvers/zod';
import { useForm, type UseFormReturn } from 'react-hook-form';
import { toast } from '@/lib/toast';
import { ApiError } from '@/lib/api-client';
import type { ResourceFormConfig } from '@/components/platform/resource-form';
import { broadcastService } from '@/services/broadcast-service';
import { useBroadcast } from '@/hooks/use-broadcast';
import { useBroadcastActions } from './use-broadcast-actions';
import { broadcastFormPath, broadcastsListPath } from './paths';
import { broadcastFormSchema, EMPTY_BROADCAST_FORM_VALUES, type BroadcastFormValues } from './broadcast-schema';
import type { Broadcast, CreateBroadcastInput } from '@/types/omnichannel';

function toFormValues(row: Broadcast | null): BroadcastFormValues {
  if (!row) return EMPTY_BROADCAST_FORM_VALUES;
  return {
    name: row.name,
    labels: row.labels,
    channelId: row.channelId,
    audience: row.audience,
    templateId: row.templateId,
    bindings: row.bindings,
    scheduleMode: row.status === 'SCHEDULED' ? 'schedule' : 'now',
    scheduledAt: row.scheduledAt,
  };
}

function toCreateInput(values: BroadcastFormValues): CreateBroadcastInput {
  return {
    name: values.name,
    labels: values.labels,
    channelId: values.channelId,
    audience: values.audience,
    templateId: values.templateId,
    bindings: values.bindings,
    scheduledAt: values.scheduleMode === 'schedule' ? values.scheduledAt : null,
  };
}

function describe(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return 'Something went wrong. Please try again.';
}

export interface UseBroadcastFormResult {
  config: ResourceFormConfig<Broadcast> | null;
  form: UseFormReturn<BroadcastFormValues>;
  isLoading: boolean;
  notFound: boolean;
  workspaceId: string | null;
  broadcast: Broadcast | null;
  creating: boolean;
  /** Ensures the in-progress draft has a real id (creates it once, on first
   *  call) - used by Test send / Send-now-before-first-save so a not-yet-
   *  persisted broadcast can still act. Returns null on validation failure. */
  ensureDraftId: () => Promise<string | null>;
  /** Send/Schedule from the Review section's primary action (creates the
   *  draft first if needed, then transitions status and navigates to the
   *  detail page). */
  sendOrSchedule: () => Promise<void>;
  sending: boolean;
}

export function useBroadcastForm(
  workspaceId: string | null,
  broadcastId: string | undefined,
  initialEditing: boolean,
): UseBroadcastFormResult {
  const router = useRouter();
  const creating = !broadcastId;
  const { broadcast, loading, notFound, refresh } = useBroadcast(workspaceId, broadcastId);
  const actions = useBroadcastActions(workspaceId);
  const [savedId, setSavedId] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  const form = useForm<BroadcastFormValues>({
    mode: 'onTouched',
    resolver: zodResolver(broadcastFormSchema),
    defaultValues: EMPTY_BROADCAST_FORM_VALUES,
  });

  useEffect(() => {
    if (creating) {
      form.reset(EMPTY_BROADCAST_FORM_VALUES);
      return;
    }
    if (broadcast) form.reset(toFormValues(broadcast));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [creating, broadcast]);

  const ensureDraftId = useCallback(async (): Promise<string | null> => {
    if (savedId) return savedId;
    if (!creating && broadcastId) return broadcastId;
    if (!workspaceId) return null;
    const valid = await form.trigger(['name', 'channelId', 'templateId', 'audience', 'bindings']);
    if (!valid) return null;
    try {
      const created = await broadcastService.create(workspaceId, toCreateInput(form.getValues()));
      setSavedId(created.id);
      return created.id;
    } catch (error) {
      toast.error(describe(error));
      return null;
    }
  }, [savedId, creating, broadcastId, workspaceId, form]);

  const sendOrSchedule = useCallback(async () => {
    if (!workspaceId) return;
    const valid = await form.trigger();
    if (!valid) return;
    setSending(true);
    try {
      const id = await ensureDraftId();
      if (!id) return;
      const values = form.getValues();
      await broadcastService.send(workspaceId, id, values.scheduleMode === 'schedule' ? values.scheduledAt : null);
      toast.success(values.scheduleMode === 'now' ? 'Broadcast is sending.' : 'Broadcast scheduled.');
      router.push(broadcastFormPath(id));
    } catch (error) {
      toast.error(describe(error));
    } finally {
      setSending(false);
    }
  }, [workspaceId, form, ensureDraftId, router]);

  const config = useMemo<ResourceFormConfig<Broadcast> | null>(() => {
    if (loading || notFound) return null;

    const onSave = async (): Promise<boolean> => {
      let ok = false;
      await form.handleSubmit(async (values) => {
        if (!workspaceId) return;
        const input = toCreateInput(values);
        if (creating) {
          const id = savedId ?? broadcastId;
          const result = id
            ? await broadcastService.update(workspaceId, id, input)
            : await broadcastService.create(workspaceId, input);
          setSavedId(result.id);
          toast.success('Broadcast saved as draft.');
          router.push(broadcastFormPath(result.id));
        } else if (broadcastId) {
          const updated = await broadcastService.update(workspaceId, broadcastId, input);
          form.reset(toFormValues(updated));
          await refresh();
          toast.success('Broadcast updated.');
        }
        ok = true;
      })();
      return ok;
    };

    const onCancel = () => {
      if (creating) router.push(broadcastsListPath);
      else form.reset(toFormValues(broadcast));
    };

    return {
      breadcrumb: [
        { label: 'Home', href: '/' },
        { label: 'Omnichannel', href: broadcastsListPath },
        { label: 'Broadcasts', href: broadcastsListPath },
        { label: creating ? 'New broadcast' : (broadcast?.name ?? 'Broadcast') },
      ],
      backHref: broadcastsListPath,
      backLabel: 'Back to broadcasts',
      title: creating ? 'New broadcast' : (broadcast?.name ?? 'Broadcast'),
      subtitle: creating ? 'Configure a WhatsApp broadcast campaign' : undefined,
      tabs: [], // built by broadcast-form-view.tsx (needs live-watched form values)
      actions,
      actionRows: broadcast ? [broadcast] : [],
      // Form-surface actions (Send/Cancel/Duplicate) call `runtime.reload()` -
      // without this the form kept showing the stale pre-action status/Edit
      // toggle after Send/Cancel (bug caught in S0 live-verify: a second
      // click correctly 409'd server-side, but the UI never refreshed to
      // show it).
      onReload: refresh,
      editable: creating || broadcast?.status === 'DRAFT',
      editPermission: 'broadcasts.manage',
      initialEditing: creating ? true : initialEditing,
      isDirty: form.formState.isDirty,
      onSave,
      onCancel,
    };
  }, [
    loading,
    notFound,
    creating,
    broadcast,
    broadcastId,
    workspaceId,
    savedId,
    actions,
    form,
    initialEditing,
    router,
    refresh,
  ]);

  return {
    config,
    form,
    isLoading: loading,
    notFound,
    workspaceId,
    broadcast,
    creating,
    ensureDraftId,
    sendOrSchedule,
    sending,
  };
}
