/**
 * Fetch the ordered legs of ONE consumption (sprint-4/12 Slice 2, AC-DLC-17/18)
 * so the Developers → Logs detail view can render the end-to-end trace timeline.
 * UI → hook → service (never a direct fetch from the component).
 */
'use client';

import { useEffect, useState } from 'react';
import { integrationLogService } from '@/services/integration-log-service';
import type { IntegrationLogItem } from '@/types/integration-logs';

export interface UseIntegrationLogTrace {
  legs: IntegrationLogItem[];
  isLoading: boolean;
}

export function useIntegrationLogTrace(traceId: string | null): UseIntegrationLogTrace {
  const [legs, setLegs] = useState<IntegrationLogItem[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(!!traceId);

  useEffect(() => {
    if (!traceId) {
      setLegs([]);
      setIsLoading(false);
      return;
    }
    let cancelled = false;
    setIsLoading(true);
    integrationLogService.getTrace(traceId).then((trace) => {
      if (cancelled) return;
      setLegs(trace?.legs ?? []);
      setIsLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [traceId]);

  return { legs, isLoading };
}
