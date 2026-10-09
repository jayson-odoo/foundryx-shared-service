'use client';

import { useCallback, useEffect, useState } from 'react';
import { toast } from '@/lib/toast';
import { listProducts, refreshManifest } from '@/services/connector-service';
import type { ConnectorProduct } from '@/types/connector';

export interface UseConnectorProducts {
  products: ConnectorProduct[];
  isLoading: boolean;
  refreshingKey: string | null;
  refresh: (key: string) => Promise<void>;
}

/** Products tab data: list + per-product manifest refresh (then reload). */
export function useConnectorProducts(): UseConnectorProducts {
  const [products, setProducts] = useState<ConnectorProduct[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [refreshingKey, setRefreshingKey] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setProducts(await listProducts());
    } catch {
      toast.error('Could not load products.');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const refresh = useCallback(
    async (key: string) => {
      setRefreshingKey(key);
      try {
        await refreshManifest(key);
        toast.success('Manifest refreshed.');
      } catch {
        toast.error('Manifest refresh failed.');
      }
      await load();
      setRefreshingKey(null);
    },
    [load],
  );

  return { products, isLoading, refreshingKey, refresh };
}
