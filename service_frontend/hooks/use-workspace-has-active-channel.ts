'use client';

/**
 * Whether a workspace has at least one active, non-trashed channel (lane
 * SS-CHANNEL-SKIP). A workspace migrated before its WhatsApp number was
 * connected has none; the composer then shows "No active channel is
 * connected to this workspace." instead of the 24-hour template lock.
 *
 * `null` = unknown (no workspace, still loading, or the list could not be
 * read - e.g. an agent without `channels.read`), so callers keep their
 * existing behaviour rather than guessing. The backend send path stays the
 * real boundary (`MessageService._resolve_channel`).
 */
import { useEffect, useState } from 'react';
import { channelService } from '@/services/channel-service';

export function useWorkspaceHasActiveChannel(workspaceId: string | null | undefined): boolean | null {
  const [hasActive, setHasActive] = useState<boolean | null>(null);

  useEffect(() => {
    setHasActive(null);
    if (!workspaceId) return;
    let cancelled = false;
    channelService
      .listByWorkspace(workspaceId)
      .then((channels) => {
        if (!cancelled) setHasActive(channels.some((c) => c.isActive && !c.isTrashed));
      })
      .catch(() => {
        if (!cancelled) setHasActive(null);
      });
    return () => {
      cancelled = true;
    };
  }, [workspaceId]);

  return hasActive;
}
