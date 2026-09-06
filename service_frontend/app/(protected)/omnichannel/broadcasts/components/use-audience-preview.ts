'use client';

/**
 * Resolved recipient count for the audience currently being configured
 * (AC-BRD-05) - refreshes whenever the source or its value changes. Debounced
 * so typing in the filter builder doesn't fire a preview per keystroke.
 */
import { useEffect, useRef, useState } from 'react';
import { broadcastService } from '@/services/broadcast-service';
import type { BroadcastAudience } from '@/types/omnichannel';

export interface UseAudiencePreviewResult {
  count: number | null;
  loading: boolean;
}

function isResolvable(audience: BroadcastAudience): boolean {
  if (audience.kind === 'segment') return !!audience.segmentId;
  if (audience.kind === 'filter') return !!audience.filter && audience.filter.rules.length > 0;
  return !!audience.contactIds && audience.contactIds.length > 0;
}

export function useAudiencePreview(workspaceId: string | null, audience: BroadcastAudience): UseAudiencePreviewResult {
  const [count, setCount] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const key = JSON.stringify(audience);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    if (!workspaceId || !isResolvable(audience)) {
      setCount(null);
      return;
    }
    setLoading(true);
    timerRef.current = setTimeout(() => {
      broadcastService
        .audiencePreview(workspaceId, audience)
        .then((res) => setCount(res.count))
        .catch(() => setCount(null))
        .finally(() => setLoading(false));
    }, 300);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId, key]);

  return { count, loading };
}
