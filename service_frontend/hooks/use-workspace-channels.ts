'use client';

/**
 * The workspace's channels, for the shared report filter bar (plan 30).
 * Extracted from the dashboard + reports pages (nit, review round 1): both
 * carried the SAME `useEffect` calling `channelService` directly from the
 * page, which is the "component reaches past the hook layer" shape the house
 * layering rule exists to prevent - and two copies drift.
 */
import { useEffect, useState } from 'react';
import { channelService } from '@/services/channel-service';
import type { Channel } from '@/types/omnichannel';

export interface UseWorkspaceChannelsResult {
  channels: Channel[];
  /** `{id, name}` pairs, the shape `ReportFilterBar` consumes. */
  options: { id: string; name: string }[];
}

export function useWorkspaceChannels(workspaceId: string | null): UseWorkspaceChannelsResult {
  const [channels, setChannels] = useState<Channel[]>([]);

  useEffect(() => {
    if (!workspaceId) {
      setChannels([]);
      return;
    }
    let cancelled = false;
    channelService
      .listByWorkspace(workspaceId)
      .then((res) => !cancelled && setChannels(res))
      .catch(() => !cancelled && setChannels([]));
    return () => {
      cancelled = true;
    };
  }, [workspaceId]);

  return { channels, options: channels.map((c) => ({ id: c.id, name: c.name })) };
}
