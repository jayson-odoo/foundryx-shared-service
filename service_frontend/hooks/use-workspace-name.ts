'use client';

/**
 * Resolve an omnichannel workspace id → its human-readable name (sprint-4/12
 * enhancement - the Developer Logs detail shows the workspace NAME, not a raw
 * uuid).
 *
 * Layering note: the Developer Logs console is CORE, workspaces are a MODULE
 * concern - so the name is resolved on the FRONTEND via the existing
 * `workspaceService` (`GET /omnichannel/workspaces/{id}`) rather than making the
 * core read service import a module table. UI → hook → service.
 *
 * An unresolvable id (deleted workspace, or omnichannel not installed) resolves
 * to `null`; the caller falls back to the raw id / an em-dash.
 */
import { useEffect, useState } from 'react';
import { workspaceService } from '@/services/workspace-service';

export interface WorkspaceNameState {
  /** The resolved name, or null while loading / when unresolvable. */
  name: string | null;
  loading: boolean;
}

export function useWorkspaceName(workspaceId: string | null | undefined): WorkspaceNameState {
  const [name, setName] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(Boolean(workspaceId));

  useEffect(() => {
    if (!workspaceId) {
      setName(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    workspaceService
      .get(workspaceId)
      .then((ws) => {
        if (!cancelled) setName(ws?.name ?? null);
      })
      .catch(() => {
        if (!cancelled) setName(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [workspaceId]);

  return { name, loading };
}
