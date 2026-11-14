'use client';

import { useCallback, useState } from 'react';
import { channelService } from '@/services/channel-service';
import type { ReplaceTokenResult } from '@/types/omnichannel';

export const REPLACE_FAILED_MESSAGE = 'Could not replace the token. Please try again.';

export interface UseReplaceChannelTokenResult {
  /** Resolves with the saved channel, or null when refused or failed (see `error`). */
  replace: (accessToken: string) => Promise<ReplaceTokenResult | null>;
  saving: boolean;
  error: string | null;
  clearError: () => void;
}

/** Replace a channel's access token. A 422 carries fixed text from the server; any other failure reads as a generic retry. */
export function useReplaceChannelToken(channelId: string): UseReplaceChannelTokenResult {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const replace = useCallback(
    async (accessToken: string) => {
      setSaving(true);
      setError(null);
      try {
        return await channelService.replaceChannelToken(channelId, accessToken);
      } catch (err) {
        const status = (err as { status?: number }).status;
        setError(status === 422 && err instanceof Error ? err.message : REPLACE_FAILED_MESSAGE);
        return null;
      } finally {
        setSaving(false);
      }
    },
    [channelId],
  );

  const clearError = useCallback(() => setError(null), []);
  return { replace, saving, error, clearError };
}
