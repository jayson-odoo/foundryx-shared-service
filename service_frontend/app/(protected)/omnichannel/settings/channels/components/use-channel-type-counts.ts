'use client';

import { useEffect, useState } from 'react';
import { channelService } from '@/services/channel-service';
import { CHANNEL_TYPES } from '@/lib/channel-capabilities';
import type { ChannelType } from '@/types/omnichannel';

export type ChannelTypeCounts = Record<ChannelType, number> | null;

/**
 * Foundryx UIUX switch only: how many active channels of each type exist,
 * for the "Connect a service" cards' chips. One read of the channel list
 * (the same endpoint the list uses); re-read when `reloadKey` changes.
 * Null while loading or when the read fails (the cards then show no chip).
 */
export function useChannelTypeCounts(reloadKey: number): ChannelTypeCounts {
  const [counts, setCounts] = useState<ChannelTypeCounts>(null);
  useEffect(() => {
    let active = true;
    channelService
      .list({ page: 0, pageSize: 100, statusView: 'active' })
      .then((r) => {
        if (!active) return;
        const next = Object.fromEntries(CHANNEL_TYPES.map((t) => [t, 0])) as Record<ChannelType, number>;
        r.data.forEach((c) => {
          next[c.channelType] = (next[c.channelType] ?? 0) + 1;
        });
        setCounts(next);
      })
      .catch(() => active && setCounts(null));
    return () => {
      active = false;
    };
  }, [reloadKey]);
  return counts;
}
