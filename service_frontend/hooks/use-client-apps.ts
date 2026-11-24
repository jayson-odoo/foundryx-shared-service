'use client';

import { useCallback, useEffect, useState } from 'react';
import type {
  ClientApp,
  CreateClientAppInput,
  UpdateClientAppInput,
} from '@/types/omnichannel';
import { clientAppsService } from '@/services/client-apps-service';

export interface UseClientAppsResult {
  apps: ClientApp[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  create: (input: CreateClientAppInput) => Promise<ClientApp>;
  rename: (id: string, input: UpdateClientAppInput) => Promise<ClientApp>;
  moveWorkspace: (
    targetClientAppId: string,
    workspaceId: string,
  ) => Promise<ClientApp>;
}

/** Client apps for the Client apps settings screen - list + create/rename/move,
 * each write followed by a full refresh (small, tenant-scoped set). */
export function useClientApps(): UseClientAppsResult {
  const [apps, setApps] = useState<ClientApp[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setApps(await clientAppsService.list());
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load client apps.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const create = useCallback(
    async (input: CreateClientAppInput) => {
      const app = await clientAppsService.create(input);
      await refresh();
      return app;
    },
    [refresh],
  );

  const rename = useCallback(
    async (id: string, input: UpdateClientAppInput) => {
      const app = await clientAppsService.rename(id, input);
      await refresh();
      return app;
    },
    [refresh],
  );

  const moveWorkspace = useCallback(
    async (targetClientAppId: string, workspaceId: string) => {
      const app = await clientAppsService.moveWorkspace(
        targetClientAppId,
        workspaceId,
      );
      await refresh();
      return app;
    },
    [refresh],
  );

  return { apps, loading, error, refresh, create, rename, moveWorkspace };
}
