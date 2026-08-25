'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  embedConfigService,
  type EmbedConfig,
} from '@/services/embed-config-service';

export interface UseEmbedConfig {
  config: EmbedConfig | null;
  loading: boolean;
  error: string | null;
  /** Provision the embed connection (idempotent). */
  enable: () => Promise<void>;
  /** Rotate the secret; resolves with the plaintext (shown once). */
  rotateSecret: () => Promise<string>;
  /** Replace the allowed parent origins (server validates). */
  setOrigins: (origins: string[]) => Promise<void>;
  reload: () => Promise<void>;
}

/**
 * Loads + mutates the tenant's embed-access config. The screen reads state ONLY
 * through this hook - the UI never touches the service/api-client directly.
 */
export function useEmbedConfig(): UseEmbedConfig {
  const [config, setConfig] = useState<EmbedConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setConfig(await embedConfigService.get());
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load embed access.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const enable = useCallback(async () => {
    setConfig(await embedConfigService.enable());
  }, []);

  const rotateSecret = useCallback(async () => {
    const { embedSecret } = await embedConfigService.rotateSecret();
    // Reflect hasSecret without leaking the plaintext into shared state.
    setConfig((c) => (c ? { ...c, hasSecret: true } : c));
    return embedSecret;
  }, []);

  const setOrigins = useCallback(async (origins: string[]) => {
    setConfig(await embedConfigService.setOrigins(origins));
  }, []);

  return { config, loading, error, enable, rotateSecret, setOrigins, reload };
}
