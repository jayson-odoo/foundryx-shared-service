'use client';

import { useCallback, useState } from 'react';
import { ApiError } from '@/lib/api-client';
import { planner3dService } from '@/services/planner3d-service';
import type { Planner3dEvent, Planner3dKeyCreated, Planner3dReceiverCreated } from '@/types/planner3d';

/**
 * Planner 3D hooks (lane PLANNER-3D-S1) - the Keys / Receivers screens' way to the
 * service layer (UI -> hook -> service -> api-client). Lists read through their
 * ResourceList fetchers; these cover the create mutations.
 */

/** Plain message for a failed call: the backend's `{code, message}` detail, else the error text. */
export function planner3dErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    const detail = err.detail as { message?: unknown } | undefined;
    if (detail && typeof detail.message === 'string' && detail.message) return detail.message;
    if (err.message) return err.message;
  }
  return fallback;
}

function useBusy<A extends unknown[], R>(fn: (...args: A) => Promise<R>) {
  const [busy, setBusy] = useState(false);
  const run = useCallback(
    async (...args: A): Promise<R> => {
      setBusy(true);
      try {
        return await fn(...args);
      } finally {
        setBusy(false);
      }
    },
    [fn],
  );
  return { busy, run };
}

export function useCreatePlanner3dKey(): { creating: boolean; create: (name: string) => Promise<Planner3dKeyCreated> } {
  const { busy, run } = useBusy(planner3dService.createKey);
  return { creating: busy, create: run };
}

export function useCreatePlanner3dReceiver(): {
  creating: boolean;
  create: (url: string, events: Planner3dEvent[]) => Promise<Planner3dReceiverCreated>;
} {
  const { busy, run } = useBusy(planner3dService.createReceiver);
  return { creating: busy, create: run };
}
