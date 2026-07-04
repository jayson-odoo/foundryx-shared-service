'use client';

import { useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { PlugZap, Pencil, PowerOff, RotateCcw, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import type { ResourceAction } from '@/components/platform/resource-list';
import { channelService } from '@/services/channel-service';
import type { Channel } from '@/types/omnichannel';
import { channelFormHref } from './paths';

/**
 * The Channel action registry — one set surfaced in the row "…" menu, the bulk
 * toolbar, and the form "…" menu (plan 04 §7). Channels are CREATED via the
 * Connect wizard, not an action; here we edit / test / disconnect.
 */
export function useChannelActions(): ResourceAction<Channel>[] {
  const router = useRouter();

  return useMemo<ResourceAction<Channel>[]>(() => {
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
        id: 'disconnect',
        label: 'Disconnect',
        icon: PowerOff,
        tone: 'destructive',
        permission: 'channels.manage',
        surfaces: { row: true, bulk: true, form: true },
        // Active (non-trashed) channels only → moves them to the Trashed view.
        isVisible: (rows) => rows.length > 0 && rows.every((r) => !r.isTrashed),
        confirm: {
          title: 'Disconnect channel?',
          description:
            'The channel will stop sending and receiving messages and move to Trashed. You can reconnect it later via Connect with Facebook.',
          confirmLabel: 'Disconnect',
        },
        run: async (rows, rt) => {
          await channelService.disconnect(ids(rows));
          toast.success(`Disconnected ${rows.length} channel(s).`);
          rt.reload();
        },
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
        // Only from the Trashed view — hard delete.
        isVisible: (rows) => rows.length > 0 && rows.every((r) => r.isTrashed),
        confirm: {
          title: 'Delete channel permanently?',
          description:
            'This permanently removes the channel and its configuration. This cannot be undone.',
          confirmLabel: 'Delete',
        },
        run: async (rows, rt) => {
          await channelService.remove(ids(rows));
          toast.success(`Deleted ${rows.length} channel(s).`);
          rt.reload();
        },
      },
    ];
  }, [router]);
}
