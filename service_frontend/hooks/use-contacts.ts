'use client';

/**
 * Contacts-module workspace resolution (plan 26, D-A2-10) - mirrors the
 * Inbox host's workspace resolution (default workspace first) so the list,
 * detail and create routes all resolve the SAME active workspace. Also
 * exposes the full workspace list so a page can render a workspace
 * `SearchSelect` in its header - ONLY when the tenant has more than one
 * workspace (the segment control already occupies the list toolbar).
 */
import { useEffect, useState } from 'react';
import { workspaceService } from '@/services/workspace-service';
import type { Workspace } from '@/types/omnichannel';

export interface UseActiveWorkspaceResult {
  workspaceId: string | null;
  workspaces: Workspace[];
  /** True once the initial resolution has settled (id may still be null if
   *  the tenant has no workspace). */
  ready: boolean;
  setWorkspaceId: (id: string) => void;
}

export function useActiveWorkspace(): UseActiveWorkspaceResult {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    workspaceService
      .list({ page: 0, pageSize: 50 })
      .then((res) => {
        if (cancelled) return;
        setWorkspaces(res.data);
        const ws = res.data.find((w) => w.isDefault) ?? res.data[0];
        setWorkspaceId(ws?.id ?? null);
      })
      .catch(() => {
        if (!cancelled) {
          setWorkspaces([]);
          setWorkspaceId(null);
        }
      })
      .finally(() => !cancelled && setReady(true));
    return () => {
      cancelled = true;
    };
  }, []);

  return { workspaceId, workspaces, ready, setWorkspaceId };
}
