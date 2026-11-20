'use client';

import { useCallback, useEffect, useState } from 'react';
import type { UpdateWebchatConfigInput, WebchatConfig } from '@/types/omnichannel';
import { webchatService } from '@/services/webchat-service';

export interface UseWebchatConfigResult {
  config: WebchatConfig | null;
  isLoading: boolean;
  /** Set only when the initial load fails - never populated by a save error
   *  (saves report through `lib/toast` at the call site instead). */
  error: string | null;
  refresh: () => void;
  save: (input: UpdateWebchatConfigInput) => Promise<WebchatConfig>;
  rotateSecret: () => Promise<string>;
}

/**
 * Widget configuration for one `WEBCHAT` channel (plan 34 / A7b) - backs both
 * the Configuration tab's read-only widget-key/origins block (AC-WEB-03) and
 * the Widget tab's editable appearance/greeting/pre-chat fields (AC-WEB-04).
 * `enabled=false` (a non-`WEBCHAT` channel, or the channel not loaded yet)
 * skips the fetch entirely rather than the caller conditionally invoking the
 * hook - React hooks must run unconditionally every render.
 */
export function useWebchatConfig(channelId: string, enabled: boolean): UseWebchatConfigResult {
  const [config, setConfig] = useState<WebchatConfig | null>(null);
  const [isLoading, setIsLoading] = useState(enabled);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    if (!enabled || !channelId) {
      setConfig(null);
      setIsLoading(false);
      setError(null);
      return;
    }
    let active = true;
    setIsLoading(true);
    setError(null);
    webchatService
      .getConfig(channelId)
      .then((c) => active && setConfig(c))
      .catch(() => active && setError('Could not load the widget configuration.'))
      .finally(() => active && setIsLoading(false));
    return () => {
      active = false;
    };
  }, [channelId, enabled, reloadToken]);

  const refresh = useCallback(() => setReloadToken((t) => t + 1), []);

  const save = useCallback(
    async (input: UpdateWebchatConfigInput) => {
      const updated = await webchatService.updateConfig(channelId, input);
      setConfig(updated);
      return updated;
    },
    [channelId],
  );

  const rotateSecret = useCallback(async () => {
    const { widgetSecret } = await webchatService.rotateSecret(channelId);
    return widgetSecret;
  }, [channelId]);

  return { config, isLoading, error, refresh, save, rotateSecret };
}
