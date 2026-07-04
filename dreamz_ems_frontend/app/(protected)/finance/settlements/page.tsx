'use client';

/** Global Settlements list (sprint-4/07 Cluster F slice 4, AC-07-46/47). Every
 * agency give-back settlement for the tenant. The three-line net (gross −
 * gateway fees − fee = net) is summarised per row; the lifecycle is driven from
 * the event's Settlement tab. Resource shell, REAL finance data. */
import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import {
  Toolbar,
  ToolbarDescription,
  ToolbarHeading,
  ToolbarPageTitle,
} from '@/partials/common/toolbar';
import { Container } from '@/components/common/container';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { Badge } from '@/components/ui/badge';
import { RequirePermission } from '@/components/common/require-permission';
import { ResourceList, type ResourceListConfig } from '@/components/platform/resource-list';
import { useDatetime } from '@/hooks/use-datetime';
import { financeService } from '@/services/finance-service';
import { formatMoney } from '@/lib/money';
import type { Settlement } from '@/types/registration';

const CURRENCY = 'MYR';

function settlementVariant(key: string | null): 'secondary' | 'primary' | 'success' {
  if (key === 'remitted') return 'success';
  if (key === 'approved') return 'primary';
  return 'secondary';
}

export default function SettlementsPage() {
  const { formatDateTime } = useDatetime();

  const config = useMemo<ResourceListConfig<Settlement>>(() => {
    const columns: ColumnDef<Settlement>[] = [
      {
        id: 'kind',
        accessorFn: (r) => r.kind,
        header: ({ column }) => <DataGridColumnHeader title="Kind" column={column} />,
        cell: ({ row }) => (
          <Badge variant={row.original.kind === 'PRIMARY' ? 'primary' : 'secondary'} appearance="light" size="sm">
            {row.original.kind === 'PRIMARY' ? 'Primary' : 'Adjustment'}
          </Badge>
        ),
        size: 120,
        enableSorting: false,
      },
      {
        id: 'gross',
        accessorFn: (r) => r.grossCollected,
        header: ({ column }) => <DataGridColumnHeader title="Gross" column={column} />,
        cell: ({ row }) => <span>{formatMoney(row.original.grossCollected, CURRENCY)}</span>,
        size: 120,
        enableSorting: false,
      },
      {
        id: 'fees',
        accessorFn: (r) => r.gatewayFees,
        header: ({ column }) => <DataGridColumnHeader title="Gateway fees" column={column} />,
        cell: ({ row }) => <span className="text-muted-foreground">{formatMoney(row.original.gatewayFees, CURRENCY)}</span>,
        size: 130,
        enableSorting: false,
      },
      {
        id: 'fee',
        accessorFn: (r) => r.feeAmount,
        header: ({ column }) => <DataGridColumnHeader title="Agency fee" column={column} />,
        cell: ({ row }) => <span className="text-muted-foreground">{formatMoney(row.original.feeAmount, CURRENCY)}</span>,
        size: 120,
        enableSorting: false,
      },
      {
        id: 'net',
        accessorFn: (r) => r.netPayable,
        header: ({ column }) => <DataGridColumnHeader title="Net payable" column={column} />,
        cell: ({ row }) => <span className="font-medium">{formatMoney(row.original.netPayable, CURRENCY)}</span>,
        size: 130,
        enableSorting: false,
      },
      {
        id: 'status',
        accessorFn: (r) => r.statusLabel,
        header: ({ column }) => <DataGridColumnHeader title="Status" column={column} />,
        cell: ({ row }) => (
          <Badge variant={settlementVariant(row.original.statusKey)} appearance="light" size="sm">
            {row.original.statusLabel ?? '—'}
          </Badge>
        ),
        size: 120,
        enableSorting: false,
      },
      {
        id: 'generatedAt',
        accessorFn: (r) => r.generatedAt,
        header: ({ column }) => <DataGridColumnHeader title="Generated" column={column} />,
        cell: ({ row }) => <span className="text-muted-foreground">{formatDateTime(row.original.generatedAt)}</span>,
        size: 170,
        enableSorting: false,
      },
    ];
    return {
      viewKey: 'finance.settlements',
      getRowId: (r) => r.id,
      rowHref: () => '#',
      fetcher: (q) => financeService.listSettlementsQuery(q),
      exporter: async () => '',
      searchPlaceholder: 'Search settlements…',
      enableStatusViews: false,
      columns,
      filterFields: [],
      exportColumns: [],
      actions: [],
    };
  }, [formatDateTime]);

  return (
    <RequirePermission permission="settlements.read">
      <Container width="fluid">
        <Toolbar>
          <ToolbarHeading>
            <ToolbarPageTitle />
            <ToolbarDescription>Agency give-back settlements across events.</ToolbarDescription>
          </ToolbarHeading>
        </Toolbar>
      </Container>
      <Container width="fluid">
        <ResourceList config={config} />
      </Container>
    </RequirePermission>
  );
}
