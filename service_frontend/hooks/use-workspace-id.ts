'use client';

/**
 * Resolve the tenant's default (or first) messaging workspace - the same
 * resolution the Inbox host page does (plan 05 §6). Broadcasts is a
 * single-workspace surface for v1 (no switcher yet), so every Broadcasts
 * route shares this one small hook instead of repeating the lookup.
 */
import { useEffect, useState } from 'react';
import { workspaceService } from '@/services/workspace-service';

export interface UseWorkspaceIdResult {
  workspaceId: string | null;
  loading: boolean;
}

export function useWorkspaceId(): UseWorkspaceIdResult {
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    workspaceService
      .list({ page: 0, pageSize: 50 })
      .then((res) => {
        if (!active) return;
        const ws = res.data.find((w) => w.isDefault) ?? res.data[0];
        setWorkspaceId(ws?.id ?? null);
      })
      .catch(() => active && setWorkspaceId(null))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, []);

  return { workspaceId, loading };
}
