'use client';

/**
 * The workspace's contact lifecycle stages (plan 26) - backs the Lifecycle
 * filter field's options, the create-form default stage, and the bulk "Move
 * lifecycle" picker. Reads the SAME scoped status-engine graph the A1
 * `LifecycleMove` panel uses (`entityType: 'omnichannel_contact_lifecycle'`), already
 * real - never a hardcoded stage list.
 */
import { useEffect, useState } from 'react';
import { statusEngineService } from '@/services/status-engine-service';

export interface LifecycleStageOption {
  id: string;
  key: string;
  label: string;
  color: string;
  isInitial: boolean;
  isTerminal: boolean;
  isArchived: boolean;
}

const CONTACT_ENTITY_TYPE = 'omnichannel_contact_lifecycle';

export function useContactLifecycleStages(workspaceId: string | null): {
  stages: LifecycleStageOption[];
  loading: boolean;
} {
  const [stages, setStages] = useState<LifecycleStageOption[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setStages([]);
    if (!workspaceId) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    statusEngineService
      .graph(CONTACT_ENTITY_TYPE, workspaceId)
      .then((graph) => {
        if (cancelled) return;
        setStages(
          graph.statuses.map((s) => ({
            id: s.id,
            key: s.key,
            label: s.label,
            color: s.color,
            isInitial: s.isInitial,
            isTerminal: s.isTerminal,
            isArchived: s.isArchived,
          })),
        );
      })
      .catch(() => !cancelled && setStages([]))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [workspaceId]);

  return { stages, loading };
}
