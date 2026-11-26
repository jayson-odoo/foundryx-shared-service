'use client';

import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Check, Minus } from 'lucide-react';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { ClampedText } from '@/components/platform/clamped-text';
import { ResourceList } from '@/components/platform/resource-list';
import { embeddedListConfig } from '@/components/platform/resource-list/embedded-list-config';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import { applyClientQuery, type ClientListSpec } from '@/lib/client-list-query';
import { hubConnectorService } from '@/services/hub-connector-service';
import type { HubCustomer, PreviewItem } from '@/types/hub-connector';
import type { ListQuery, ListResult } from '@/types/resource';

const spec: ClientListSpec<PreviewItem> = {
  searchText: (i) => [i.name, i.code, i.brand.name],
  value: (i, field) => {
    switch (field) {
      case 'item':
        return i.name.toLowerCase();
      case 'brand':
        return i.brand.name.toLowerCase();
      case 'gotStock':
        return i.gotStock ? 1 : 0;
      case 'gotIncoming':
        return i.gotIncoming ? 1 : 0;
      case 'price':
        return i.price ?? null;
      default:
        return null;
    }
  },
};

function YesNo({ yes }: { yes: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-sm">
      {yes ? <Check className="size-4 text-success" aria-hidden /> : <Minus className="size-4 text-muted-foreground" aria-hidden />}
      {yes ? 'Yes' : 'No'}
    </span>
  );
}

/** What one customer sees on the hub; the Price column only while the hub shows price. */
export function usePreviewListConfig(
  hubId: string,
  customerId: string,
  showPrice: boolean,
): ResourceListConfig<PreviewItem> {
  return useMemo(() => {
    const col = (id: string, title: string, size: number, cell: ColumnDef<PreviewItem>['cell']): ColumnDef<PreviewItem> => ({
      id,
      accessorFn: (r) => spec.value(r, id) as string | number | null,
      meta: { headerTitle: title },
      header: ({ column }) => <DataGridColumnHeader title={title} column={column} />,
      cell,
      size,
      enableSorting: true,
    });
    const columns: ColumnDef<PreviewItem>[] = [
      col('item', 'Item', 240, ({ row }) => (
        <div className="flex min-w-0 flex-col">
          <ClampedText text={row.original.name} lines={1} className="font-medium" />
          <ClampedText text={row.original.code} lines={1} className="font-mono text-xs text-muted-foreground" />
        </div>
      )),
      col('brand', 'Brand', 160, ({ row }) => <ClampedText text={row.original.brand.name} lines={1} className="text-sm" />),
      col('gotStock', 'Got stock', 110, ({ row }) => <YesNo yes={row.original.gotStock} />),
      col('gotIncoming', 'Got incoming', 130, ({ row }) => <YesNo yes={row.original.gotIncoming} />),
    ];
    if (showPrice) {
      columns.push(
        col('price', 'Price', 120, ({ row }) => (
          <span className="text-sm">
            {row.original.price == null ? '-' : `${row.original.currency ?? ''} ${row.original.price}`.trim()}
          </span>
        )),
      );
    }
    const fetcher = async (query: ListQuery): Promise<ListResult<PreviewItem>> => {
      const { items } = await hubConnectorService.previewCustomer(hubId, customerId);
      return applyClientQuery(items, query, spec);
    };
    return embeddedListConfig<PreviewItem>({
      viewKey: 'hub-connector.preview',
      columns,
      fetcher,
      getRowId: (i) => i.code,
      rowHref: () => '#',
      searchPlaceholder: 'Search items…',
      defaultSort: { id: 'item', desc: false },
    });
  }, [hubId, customerId, showPrice]);
}

export interface PreviewDialogProps {
  hubId: string;
  customer: HubCustomer | null;
  showPrice: boolean;
  onClose: () => void;
}

function PreviewBody({ hubId, customerId, showPrice }: { hubId: string; customerId: string; showPrice: boolean }) {
  const config = usePreviewListConfig(hubId, customerId, showPrice);
  return <ResourceList config={config} hideHeader />;
}

/** Centred dialog with the items the customer sees. */
export function PreviewDialog({ hubId, customer, showPrice, onClose }: PreviewDialogProps) {
  return (
    <Dialog open={customer !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-3xl" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>{customer ? `What ${customer.customerName} sees` : 'Preview'}</DialogTitle>
        </DialogHeader>
        <DialogBody>
          {customer && <PreviewBody hubId={hubId} customerId={customer.id} showPrice={showPrice} />}
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}
