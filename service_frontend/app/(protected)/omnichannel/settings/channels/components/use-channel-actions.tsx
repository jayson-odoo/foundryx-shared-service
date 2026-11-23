'use client';

import { useFxActor } from './use-fx-actor';
import { useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { KeyRound, PlugZap, Pencil, PowerOff, RotateCcw, Trash2 } from 'lucide-react';
import { toast } from '@/lib/toast';
import { useFx } from '@/hooks/use-fx';
import type { ResourceAction } from '@/components/platform/resource-list';
import { channelService } from '@/services/channel-service';
import type { Channel } from '@/types/omnichannel';
import { channelFormHref } from './paths';
import { setChannelTestResult, setChannelTesting, type ChannelTestResult } from './channel-test-results';

/**
 * The Channel action registry - one set surfaced in the row "…" menu, the bulk
 * toolbar, and the form "…" menu (plan 04 §7). Channels are CREATED via the
 * Connect wizard, not an action; here we edit / test / disconnect.
 */
export interface UseChannelActionsOptions {
  /** Open the Replace token dialog for a channel (the parent owns the dialog state). */
  onReplaceToken?: (channel: Channel) => void;
}

export function useChannelActions({ onReplaceToken }: UseChannelActionsOptions = {}): ResourceAction<Channel>[] {
  const router = useRouter();
  const fx = useFx();
  const byWhom = useFxActor();

  const actions = useMemo<ResourceAction<Channel>[]>(() => {
    const ids = (rows: Channel[]) => rows.map((r) => r.id);

    return [
      {
        id: 'edit',
        label: 'Edit',
        icon: Pencil,
        permission: 'channels.manage',
        surfaces: { row: true },
        run: ([channel], rt) => {
          if (!channel) return;
          router.push(channelFormHref(channel.id, { ctx: rt.ctx, index: rt.index, edit: true }));
        },
      },
      {
        id: 'test-connection',
        label: 'Test connection',
        icon: PlugZap,
        permission: 'channels.manage',
        surfaces: { row: true, form: true },
        isVisible: (rows) => rows.length === 1 && rows.every((r) => !r.isTrashed),
        run: async ([channel]) => {
          if (!channel) return;
          const res = await channelService.testConnection(channel.id);
          if (res.ok) toast.success(res.message);
          else toast.error(res.message);
        },
      },
      {
        id: 'replace-token',
        label: 'Replace token',
        icon: KeyRound,
        permission: 'channels.manage',
        surfaces: { row: true, form: true },
        isVisible: (rows) =>
          rows.length === 1 && rows.every((r) => r.channelType === 'WHATSAPP' && !r.isTrashed),
        // Opens the dialog (a `run`, not a confirm): the list page or the record
        // owns the dialog, like `onConnect` on the list config.
        run: ([channel]) => {
          if (channel) onReplaceToken?.(channel);
        },
      },
      {
        id: 'disconnect',
        label: 'Disconnect',
        icon: PowerOff,
        tone: 'destructive',
        permission: 'channels.manage',
        surfaces: { row: true, bulk: true, form: true },
        // Active (non-trashed) channels only → moves them to the Trashed view.
        isVisible: (rows) => rows.length > 0 && rows.every((r) => !r.isTrashed),
        // Grace-window deferred action (sprint-4/23, T5 fix round 1, item
        // 15) - no confirm, no `run` (the registered `channels.disconnect`
        // handler commits it server-side).
        deferred: { actionKey: 'channels.disconnect', entityType: 'channel' },
      },
      {
        id: 'restore',
        label: 'Restore',
        icon: RotateCcw,
        permission: 'channels.manage',
        surfaces: { row: true, bulk: true },
        // Trashed channels only.
        isVisible: (rows) => rows.length > 0 && rows.every((r) => r.isTrashed),
        run: async (rows, rt) => {
          await channelService.restore(ids(rows));
          toast.success(`Restored ${rows.length} channel(s).`);
          rt.reload();
        },
      },
      {
        id: 'delete',
        label: 'Delete permanently',
        icon: Trash2,
        tone: 'destructive',
        permission: 'channels.manage',
        surfaces: { row: true, bulk: true },
        // Only from the Trashed view - hard delete.
        isVisible: (rows) => rows.length > 0 && rows.every((r) => r.isTrashed),
        // Grace-window deferred action - no confirm, no `run` (the
        // registered `channels.delete` handler commits it server-side).
        deferred: { actionKey: 'channels.delete', entityType: 'channel' },
      },
    ];
  }, [router, onReplaceToken]);

  // Foundryx UIUX switch only: the same actions and the same requests; only
  // what is said afterwards changes (the test result sits next to the
  // channel, toasts name what happened and by whom, the countdown names the
  // channel).
  return useMemo(
    () => (fx ? actions.map((a) => fxChannelAction(a, byWhom)) : actions),
    [fx, actions, byWhom],
  );
}

/** Runs Test connection for one channel and keeps the result beside it.
 *  Resolves with the result (null when the request failed). */
export async function fxTestConnection(channel: Channel): Promise<ChannelTestResult | null> {
  setChannelTesting(channel.id);
  try {
    const res = await channelService.testConnection(channel.id);
    setChannelTestResult(channel.id, res);
    return res;
  } catch {
    setChannelTestResult(channel.id, {
      ok: false,
      message: "Couldn't run the test. Try again.",
      checkedAt: new Date().toISOString(),
    });
    return null;
  }
}

function fxChannelAction(action: ResourceAction<Channel>, byWhom: string | undefined): ResourceAction<Channel> {
  if (action.id === 'test-connection') {
    return {
      ...action,
      run: async ([channel]) => {
        if (channel) await fxTestConnection(channel);
      },
    } as ResourceAction<Channel>;
  }
  if (action.id === 'restore') {
    return {
      ...action,
      run: async (rows, rt) => {
        await channelService.restore(rows.map((r) => r.id));
        toast.fxDone({
          what: rows.length === 1 ? `${rows[0].name} restored` : `${rows.length} channels restored`,
          byWhom,
        });
        rt.reload();
      },
    } as ResourceAction<Channel>;
  }
  if (action.deferred) {
    return {
      ...action,
      deferred: { ...action.deferred, fxName: (rows: Channel[]) => (rows.length === 1 ? rows[0].name : undefined) },
    };
  }
  return action;
}
