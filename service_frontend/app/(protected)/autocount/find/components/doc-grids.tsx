'use client';

import Link from 'next/link';
import { ExternalLink } from 'lucide-react';
import { type ColumnDef, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import { Badge } from '@/components/ui/badge';
import { DataGrid } from '@/components/ui/data-grid';
import { DataGridTable } from '@/components/ui/data-grid-table';
import { ClampedText } from '@/components/platform/clamped-text';
import { useDatetime } from '@/hooks/use-datetime';
import {
  dayInRange,
  formatVendorDateTime,
  formatVendorDay,
  lineColumns,
  vendorValueText,
} from '@/lib/autocount-doc-lookup';
import type { DocLookupSnapshotSighting, DocLookupVendorRecord } from '@/types/autocount-doc-lookup';
import { acPullSnapshotHref } from '../../components/autocount-meta';

export interface LinesGridProps {
  lines: DocLookupVendorRecord[];
}

/** The document's lines, verbatim, in a fixed useful column order. */
export function LinesGrid({ lines }: LinesGridProps) {
  const columns: ColumnDef<DocLookupVendorRecord>[] = lineColumns(lines).map((c) => ({
    id: c.key,
    header: c.label,
    accessorFn: (row) => row[c.key],
    cell: ({ row }) =>
      c.numeric ? (
        vendorValueText(row.original[c.key])
      ) : (
        <ClampedText text={vendorValueText(row.original[c.key])} lines={1} />
      ),
    meta: c.numeric ? { cellClassName: 'text-end tabular-nums', headerClassName: 'text-end' } : undefined,
  }));
  const table = useReactTable({
    data: lines,
    columns,
    getRowId: (_row, index) => String(index),
    getCoreRowModel: getCoreRowModel(),
  });
  return (
    <div className="overflow-auto rounded-lg border border-border" data-testid="ac-find-lines">
      <DataGrid table={table} recordCount={lines.length} emptyMessage="No lines.">
        <DataGridTable />
      </DataGrid>
    </div>
  );
}

export interface SnapshotsGridProps {
  snapshots: DocLookupSnapshotSighting[];
  /** The document's DocDate now - each snapshot says whether it is in range. */
  currentDocDate: string | null;
}

/** Every stored snapshot that held the number, with the DocDate it had then. */
export function SnapshotsGrid({ snapshots, currentDocDate }: SnapshotsGridProps) {
  const { formatDateTime } = useDatetime();
  const columns: ColumnDef<DocLookupSnapshotSighting>[] = [
    {
      id: 'snapshot',
      header: 'Snapshot',
      cell: ({ row }) => (
        <Link
          href={acPullSnapshotHref(row.original.snapshotId)}
          className="inline-flex items-center gap-1 font-medium text-primary hover:underline"
        >
          {row.original.snapshotId.slice(0, 8)}
          <ExternalLink className="size-3.5" />
        </Link>
      ),
    },
    { id: 'built', header: 'Built', cell: ({ row }) => formatDateTime(row.original.createdAt) },
    {
      id: 'range',
      header: 'Range',
      cell: ({ row }) =>
        `${formatVendorDay(row.original.fromDay)} – ${formatVendorDay(row.original.toDay)}${
          row.original.byNumber ? ' · by number' : ''
        }`,
    },
    { id: 'docDate', header: 'DocDate then', cell: ({ row }) => formatVendorDay(row.original.docDate) },
    {
      id: 'lastModified',
      header: 'Last modified then',
      cell: ({ row }) => formatVendorDateTime(row.original.lastModified),
    },
    {
      id: 'inRange',
      header: "Today's DocDate in range",
      cell: ({ row }) => {
        const inRange = dayInRange(currentDocDate, row.original.fromDay, row.original.toDay);
        return (
          <Badge variant={inRange ? 'success' : 'warning'} appearance="light" size="sm">
            {inRange ? 'Yes' : 'No'}
          </Badge>
        );
      },
    },
  ];
  const table = useReactTable({
    data: snapshots,
    columns,
    getRowId: (row) => row.snapshotId,
    getCoreRowModel: getCoreRowModel(),
  });
  return (
    <div className="overflow-auto rounded-lg border border-border" data-testid="ac-find-snapshots">
      <DataGrid table={table} recordCount={snapshots.length} emptyMessage="Not in any stored snapshot.">
        <DataGridTable />
      </DataGrid>
    </div>
  );
}
