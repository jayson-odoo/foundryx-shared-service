'use client';

import { Fragment, useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  Toolbar,
  ToolbarDescription,
  ToolbarHeading,
  ToolbarPageTitle,
} from '@/partials/common/toolbar';
import { Container } from '@/components/common/container';
import { ResourceList } from '@/components/platform/resource-list';
import { RequirePermission } from '@/components/common/require-permission';
import { useStatusGraph } from '@/hooks/use-status-engine';
import { emsService } from '@/services/ems-service';
import type { Client, Quotation } from '@/types/ems';
import { useQuotationsListConfig } from './use-quotations-list-config';

const QUOTATION_ENTITY = 'quotation';

export default function QuotationsPage() {
  const router = useRouter();
  const engine = useStatusGraph(QUOTATION_ENTITY);
  const [clients, setClients] = useState<Client[]>([]);

  useEffect(() => {
    emsService.clientOptions().then(setClients).catch(() => setClients([]));
  }, []);

  const onCreate = useCallback(() => router.push('/ems/quotations/new'), [router]);
  const onEdit = useCallback((row: Quotation) => router.push(`/ems/quotations/${row.id}`), [router]);
  const clientName = useCallback(
    (id: string) => clients.find((c) => c.id === id)?.name ?? '—',
    [clients],
  );

  const config = useQuotationsListConfig(
    useMemo(
      () => ({
        onCreate,
        onEdit,
        clientName,
        statuses: engine.graph?.statuses ?? [],
        transitions: engine.graph?.transitions ?? [],
      }),
      [onCreate, onEdit, clientName, engine.graph],
    ),
  );

  return (
    <RequirePermission permission="crm_quotations.read">
      <Fragment>
        <Container width="fluid">
          <Toolbar>
            <ToolbarHeading>
              <ToolbarPageTitle />
              <ToolbarDescription>B2B service quotes.</ToolbarDescription>
            </ToolbarHeading>
          </Toolbar>
        </Container>
        <Container width="fluid">
          <ResourceList config={config} />
        </Container>
      </Fragment>
    </RequirePermission>
  );
}
