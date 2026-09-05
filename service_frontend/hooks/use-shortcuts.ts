'use client';

/**
 * Shortcut workflows for the current thread (plan 27, AC-IVE-36/37/39) - backs
 * the drawer header's Shortcuts control. Loads once per `contactId`; `run`
 * fires the chosen workflow and returns the result for the caller to toast.
 */
import { useCallback, useEffect, useState } from 'react';

import { ApiError } from '@/lib/api-client';
import { conversationService } from '@/services/conversation-service';
import type { ShortcutItem, ShortcutRunResult } from '@/types/omnichannel';

function describe(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return 'Could not run the shortcut.';
}

export interface UseShortcutsResult {
  shortcuts: ShortcutItem[];
  isLoading: boolean;
  isRunning: boolean;
  run: (workflowId: string) => Promise<ShortcutRunResult | null>;
  /** Last run failure, so the caller can surface the server message. */
  runError: string | null;
}

export function useShortcuts(contactId: string | null | undefined): UseShortcutsResult {
  const [shortcuts, setShortcuts] = useState<ShortcutItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

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
    async (workflowId: string): Promise<ShortcutRunResult | null> => {
      if (!contactId) return null;
      setIsRunning(true);
      setRunError(null);
      try {
        return await conversationService.runShortcut(contactId, workflowId);
      } catch (error) {
        setRunError(describe(error));
        return null;
      } finally {
        setIsRunning(false);
      }
    },
    [contactId],
  );

  return { shortcuts, isLoading, isRunning, run, runError };
}
