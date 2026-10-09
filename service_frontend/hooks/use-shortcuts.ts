'use client';

/**
 * Shortcut workflows for the current thread (plan 27, AC-IVE-36/37/39) - backs
 * the drawer header's Shortcuts control. Loads once per `contactId`; `run`
 * fires the chosen workflow and returns the result for the caller to toast.
 */
import { useCallback, useEffect, useState } from 'react';

import { conversationService } from '@/services/conversation-service';
import type { ShortcutItem, ShortcutRunResult } from '@/types/omnichannel';

export interface UseShortcutsResult {
  shortcuts: ShortcutItem[];
  isLoading: boolean;
  isRunning: boolean;
  /**
   * Fires the shortcut and RETHROWS on failure (the caller reads
   * `ApiError.message` - a 409 like "unauthorized Code node" carries a plain-
   * string `detail` that `apiFetch` already promotes into `.message`, exactly
   * the pattern `lifecycle-move.tsx` uses for its 409). Only `isRunning`
   * bookkeeping happens here so the failure's own message is never swallowed
   * behind a stale render's closure.
   */
  run: (workflowId: string) => Promise<ShortcutRunResult>;
}

export function useShortcuts(contactId: string | null | undefined): UseShortcutsResult {
  const [shortcuts, setShortcuts] = useState<ShortcutItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isRunning, setIsRunning] = useState(false);

  useEffect(() => {
    if (!contactId) {
      setShortcuts([]);
      return;
    }
    let cancelled = false;
    setIsLoading(true);
    conversationService
      .listShortcuts(contactId)
      .then((list) => !cancelled && setShortcuts(list))
      .catch(() => !cancelled && setShortcuts([]))
      .finally(() => !cancelled && setIsLoading(false));
    return () => {
      cancelled = true;
    };
  }, [contactId]);

  const run = useCallback(
    async (workflowId: string): Promise<ShortcutRunResult> => {
      if (!contactId) throw new Error('No conversation selected.');
      setIsRunning(true);
      try {
        return await conversationService.runShortcut(contactId, workflowId);
      } finally {
        setIsRunning(false);
      }
    },
    [contactId],
  );

  return { shortcuts, isLoading, isRunning, run };
}
