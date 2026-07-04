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
import type { Client, SalesOrder } from '@/types/ems';
import { useSalesOrdersListConfig } from './use-sales-orders-list-config';

const SALES_ORDER_ENTITY = 'sales_order';

export default function SalesOrdersPage() {
  const router = useRouter();
  const engine = useStatusGraph(SALES_ORDER_ENTITY);
  const [clients, setClients] = useState<Client[]>([]);

  useEffect(() => {
    emsService.clientOptions().then(setClients).catch(() => setClients([]));
  }, []);

  const onCreate = useCallback(() => router.push('/ems/sales-orders/new'), [router]);
  const onEdit = useCallback((row: SalesOrder) => router.push(`/ems/sales-orders/${row.id}`), [router]);
  const clientName = useCallback(
    (id: string) => clients.find((c) => c.id === id)?.name ?? '—',
    [clients],
  );

  const config = useSalesOrdersListConfig(
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
    <RequirePermission permission="crm_sales_orders.read">
      <Fragment>
        <Container width="fluid">
          <Toolbar>
            <ToolbarHeading>
              <ToolbarPageTitle />
              <ToolbarDescription>Confirmed commercial orders.</ToolbarDescription>
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
