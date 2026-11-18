'use client';

/**
 * The integrations page with the Foundryx UIUX switch on (gap audit 12,
 * "Connected services"): a card per service in the catalog with its own
 * Connect, then the connections as cards (the list's search, filters, export
 * and actions unchanged). Connect opens the same new connection form a
 * module's settings page deep-links to, with the provider already picked;
 * every request is the legacy page's.
 */
import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Container } from '@/components/common/container';
import { PageHeader } from '@/components/platform/page-header';
import { ResourceList } from '@/components/platform/resource-list';
import { useCan } from '@/hooks/use-can';
import { integrationService } from '@/services/integration-service';
import type { IntegrationProvider } from '@/types/integration';
import { FX_TYPE_LABELS, useConnectionsListConfig } from './use-connections-list-config';
import { FxIntegrationServices } from './fx-integration-services';
import { connectionNewPath } from './paths';

/**
 * How many connections each provider has, for the service cards' chips. One
 * read of the connection list (the same endpoint the list uses); re-read when
 * `reloadKey` changes. Null while loading or when the read fails.
 */
function useProviderCounts(reloadKey: number): Record<string, number> | null {
  const [counts, setCounts] = useState<Record<string, number> | null>(null);
  useEffect(() => {
    let active = true;
    integrationService
      .list({ page: 0, pageSize: 100 })
      .then((r) => {
        if (!active) return;
        const next: Record<string, number> = {};
        r.data.forEach((c) => {
          next[c.provider] = (next[c.provider] ?? 0) + 1;
        });
        setCounts(next);
      })
      .catch(() => active && setCounts(null));
    return () => {
      active = false;
    };
  }, [reloadKey]);
  return counts;
}

export function FxIntegrationsPage() {
  const router = useRouter();
  const { can } = useCan();
  const [providers, setProviders] = useState<IntegrationProvider[]>([]);
  const [countsKey, setCountsKey] = useState(0);
  const counts = useProviderCounts(countsKey);

  useEffect(() => {
    integrationService.providers().then(setProviders).catch(() => setProviders([]));
  }, []);

  const onFxChanged = useCallback(() => setCountsKey((k) => k + 1), []);
  const config = useConnectionsListConfig({ onFxChanged });

  return (
    <Container width="fluid">
      <div className="flex flex-col gap-4">
        <PageHeader />
        <FxIntegrationServices
          providers={providers}
          counts={counts}
          typeLabel={(type) => FX_TYPE_LABELS[type] ?? type}
          canConnect={can('integrations.manage')}
          onConnect={(p) => router.push(`${connectionNewPath}?provider=${encodeURIComponent(p.provider)}`)}
        />
        <ResourceList config={config} hideHeader restoreFromCtx />
      </div>
    </Container>
  );
}
