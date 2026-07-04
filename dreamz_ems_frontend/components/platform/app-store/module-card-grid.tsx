'use client';

import { Blocks } from 'lucide-react';
import { Alert, AlertIcon, AlertTitle } from '@/components/ui/alert';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import type { StoreAction } from '@/types/app-store';
import type { UseAppStoreResult } from '@/hooks/use-app-store';
import { ModuleCard } from './module-card';

/**
 * The App Store card grid (plan 08 §8) — storefront page and console Modules
 * tab render this against the same `useAppStore()` result; only the hook's
 * `tenantId` and the `canAct` gate differ between the two surfaces.
 */
export interface ModuleCardGridProps {
  store: UseAppStoreResult;
  canAct: (action: StoreAction | 'uninstall') => boolean;
}

export function ModuleCardGrid({ store, canAct }: ModuleCardGridProps) {
  const { modules, loading, error, pending, run, uninstall } = store;

  if (loading) {
    return (
      <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3" data-testid="app-store-loading">
        {[0, 1, 2].map((i) => (
          <Card key={i}>
            <CardContent className="space-y-3 p-5">
              <Skeleton className="size-11 rounded-lg" />
              <Skeleton className="h-5 w-2/5" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-4/5" />
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {error && (
        <Alert variant="destructive" appearance="light">
          <AlertIcon />
          <AlertTitle>{error}</AlertTitle>
        </Alert>
      )}

      {modules.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center gap-2 py-16 text-center">
            <Blocks className="size-8 text-muted-foreground" />
            <p className="text-sm font-medium">No modules listed</p>
            <p className="text-sm text-muted-foreground">
              Modules appear here once they are published to this deployment.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
          {modules.map((m) => (
            <ModuleCard
              key={m.name}
              module={m}
              canAct={canAct}
              busy={pending === m.name}
              onAction={run}
              onUninstall={uninstall}
            />
          ))}
        </div>
      )}
    </div>
  );
}
