'use client';

import { useCallback, useEffect, useState } from 'react';
import { getGrant, getGrantActivity } from '@/services/connector-service';
import type { ConnectorActivity, ConnectorGrant } from '@/types/connector';

export interface UseConnectorGrant {
  grant: ConnectorGrant | null;
  activity: ConnectorActivity | null;
  isLoading: boolean;
  reload: () => void;
}

/** Grant detail data: the grant, then its activity (calls + lifecycle events). */
export function useConnectorGrant(grantId: string): UseConnectorGrant {
  const [grant, setGrant] = useState<ConnectorGrant | null>(null);
  const [activity, setActivity] = useState<ConnectorActivity | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    Promise.all([
      getGrant(grantId).catch(() => null),
      getGrantActivity(grantId).catch(() => null),
    ]).then(([g, a]) => {
      if (cancelled) return;
      setGrant(g);
      setActivity(a);
      setIsLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [grantId, reloadKey]);

  const reload = useCallback(() => setReloadKey((k) => k + 1), []);
  return { grant, activity, isLoading, reload };
}
