'use client';

/**
 * The workspace's distinct channel types (plan 26/29) - backs the Channel
 * filter field's options on both the Contacts list and the broadcasts
 * audience Filter builder (`useContactFilterFields`). Extracted out of
 * `contacts/page.tsx` (review round 1, B3) so a second surface building the
 * same field list doesn't hand-roll a second fetch.
 */
import { useEffect, useState } from 'react';
import { channelService } from '@/services/channel-service';

export interface ChannelTypeOption {
  label: string;
  value: string;
}

export function useChannelTypeOptions(workspaceId: string | null): ChannelTypeOption[] {
  const [options, setOptions] = useState<ChannelTypeOption[]>([]);

  useEffect(() => {
    if (!workspaceId) {
      setOptions([]);
      return;
    }
    channelService
      .listByWorkspace(workspaceId)
      .then((channels) => {
        const seen = new Set<string>();
        for (const c of channels) seen.add(c.channelType);
        setOptions(Array.from(seen).map((v) => ({ label: v, value: v })));
      })
      .catch(() => setOptions([]));
  }, [workspaceId]);

  return options;
}
