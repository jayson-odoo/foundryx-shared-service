'use client';

/** Global Invoices list (sprint-4/05) — every invoice for the tenant (across
 * events + CRM). REAL finance data + status engine. Click a row → the invoice
 * form opens in place (MasterDetail) with record-nav + graph-driven transitions. */
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
import type { ResourceListConfig } from '@/components/platform/resource-list';
import { MasterDetail } from '@/components/platform/resource-master-detail';
import { InvoiceDetailForm } from '@/components/platform/invoice-detail/invoice-detail-form';
import { useDatetime } from '@/hooks/use-datetime';
import { financeService } from '@/services/finance-service';
import { formatMoney } from '@/lib/money';
import { invoiceStatusVariant } from '@/lib/invoice-status';
import type { Invoice } from '@/types/registration';

export default function InvoicesPage() {
  const { formatDateTime } = useDatetime();

  const config = useMemo<ResourceListConfig<Invoice>>(() => {
    const columns: ColumnDef<Invoice>[] = [
      {
        id: 'billTo',
        accessorFn: (r) => r.billToName,
        header: ({ column }) => <DataGridColumnHeader title="Bill to" column={column} />,
        cell: ({ row }) => (
          <div className="flex items-center gap-2">
            <span className="font-medium">{row.original.billToName || row.original.billToId.slice(0, 8)}</span>
            <Badge variant="secondary" appearance="light" size="sm">{row.original.billToType}</Badge>
          </div>
        ),
        size: 240,
        enableSorting: false,
      },
      {
        id: 'total',
        accessorFn: (r) => r.total,
        header: ({ column }) => <DataGridColumnHeader title="Total" column={column} />,
        cell: ({ row }) => <span className="font-medium">{formatMoney(row.original.total, row.original.currency)}</span>,
        size: 130,
        enableSorting: false,
      },
      {
        id: 'status',
        accessorFn: (r) => r.statusLabel,
        header: ({ column }) => <DataGridColumnHeader title="Status" column={column} />,
        cell: ({ row }) => {
          const label = row.original.statusLabel ?? '—';
          return <Badge variant={invoiceStatusVariant(label)} appearance="light" size="sm">{label}</Badge>;
        },
        size: 120,
        enableSorting: false,
      },
      {
        id: 'createdAt',
        accessorFn: (r) => r.createdAt,
        header: ({ column }) => <DataGridColumnHeader title="Created" column={column} />,
        cell: ({ row }) => <span className="text-muted-foreground">{formatDateTime(row.original.createdAt)}</span>,
        size: 170,
        enableSorting: true,
      },
    ];
    return {
      viewKey: 'finance.invoices',
      getRowId: (r) => r.id,
      rowHref: () => '#',
      fetcher: (q) => financeService.listInvoicesQuery(q),
      exporter: async () => '',
      searchPlaceholder: 'Search invoices…',
      searchHints: ['Bill-to'],
      defaultSort: { id: 'createdAt', desc: true },
      enableStatusViews: false,
      columns,
      filterFields: [],
      exportColumns: [],
      actions: [],
    };
  }, [formatDateTime]);

  return (
    <RequirePermission permission="invoices.read">
      <Container width="fluid">
        <Toolbar>
          <ToolbarHeading>
            <ToolbarPageTitle />
            <ToolbarDescription>Every invoice across events and quotations.</ToolbarDescription>
          </ToolbarHeading>
        </Toolbar>
      </Container>
      <Container width="fluid">
        <MasterDetail
          config={config}
          detailRender={(r, nav) => <InvoiceDetailForm invoiceId={r.id} nav={nav} />}
        />
      </Container>
    </RequirePermission>
  );
}
