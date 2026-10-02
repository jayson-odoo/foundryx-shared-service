'use client';

import { useCallback, useEffect, useState } from 'react';
import { integrationService } from '@/services/integration-service';
import type { Connection } from '@/types/integration';

/** The connection kinds the meetings module owns (S0 plan §2). */
export const MEETINGS_PROVIDERS = ['google_dwd', 'meet_bot'] as const;
export type MeetingsProviderKey = (typeof MEETINGS_PROVIDERS)[number];

export interface UseMeetingsConnections {
  /** The tenant's connection for each meetings provider, or null if unset. */
  byProvider: Record<MeetingsProviderKey, Connection | null>;
  loading: boolean;
  error: string | null;
  reload: () => Promise<void>;
}

/**
 * The meetings module's own connections, read off the CORE connection registry
 * (S0 plan §2) - the module stores no connection of its own and the create/edit
 * form is the shared `/settings/integrations` one.
 */
export function useMeetingsConnections(): UseMeetingsConnections {
  const [byProvider, setByProvider] = useState<Record<MeetingsProviderKey, Connection | null>>({
    google_dwd: null,
    meet_bot: null,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await integrationService.list({ page: 0, pageSize: 200 });
      setByProvider({
        google_dwd: data.find((c) => c.provider === 'google_dwd') ?? null,
        meet_bot: data.find((c) => c.provider === 'meet_bot') ?? null,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load connections.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { byProvider, loading, error, reload };
}
