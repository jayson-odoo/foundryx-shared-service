'use client';

/**
 * The migration job's counts-report card (AC-MIG-08) - ONE `DataGrid` whose
 * rows are the per-entity counts (`{fetched, wouldCreate, wouldUpdate,
 * wouldSkip, errors}`), the SAME "one DataGrid, N rows" shape as
 * `jobs/[id]/failed-assets-card.tsx` (never a separate grid per row, which
 * would just be eight one-row tables).
 */
import { useMemo } from 'react';
import { type ColumnDef, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import { Card, CardContent, CardHeader, CardHeading, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { DataGrid } from '@/components/ui/data-grid';
import { DataGridTable } from '@/components/ui/data-grid-table';
import { ClampedText } from '@/components/platform/clamped-text';
import {
  MIGRATION_ENTITY_ORDER,
  type MigrationEntityCounts,
  type MigrationEntityKey,
  type MigrationReport,
} from '@/types/respondio-migration';

const ENTITY_LABEL: Record<MigrationEntityKey, string> = {
  contacts: 'Contacts',
  fields: 'Custom fields',
  tags: 'Tags',
  identities: 'Channel identities',
  messages: 'Messages',
  media: 'Media',
  events: 'Events',
  quickReplies: 'Quick replies',
};

interface EntityRow {
  key: MigrationEntityKey;
  label: string;
  counts: MigrationEntityCounts;
}

export function MigrationReportCard({ report }: { report: MigrationReport }) {
  const rows = useMemo<EntityRow[]>(
    () =>
      MIGRATION_ENTITY_ORDER.map((key) => ({
        key,
        label: ENTITY_LABEL[key],
        counts: report.entities[key],
      })),
    [report],
  );

  const columns = useMemo<ColumnDef<EntityRow>[]>(
    () => [
      { id: 'entity', header: 'Entity', cell: ({ row }) => <span className="font-medium">{row.original.label}</span> },
      { id: 'fetched', header: 'Fetched', cell: ({ row }) => row.original.counts.fetched },
      { id: 'wouldCreate', header: 'Would create', cell: ({ row }) => row.original.counts.wouldCreate },
      { id: 'wouldUpdate', header: 'Would update', cell: ({ row }) => row.original.counts.wouldUpdate },
      { id: 'wouldSkip', header: 'Would skip', cell: ({ row }) => row.original.counts.wouldSkip },
      {
        id: 'errors',
        header: 'Errors',
        cell: ({ row }) =>
          row.original.counts.errors > 0 ? (
            <Badge variant="destructive" appearance="light" size="sm">
              {row.original.counts.errors}
            </Badge>
          ) : (
            0
          ),
      },
    ],
    [],
  );

  const table = useReactTable({
    data: rows,
    columns,
    getRowId: (row) => row.key,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <Card>
      <CardHeader>
        <CardHeading>
          <CardTitle>Counts report</CardTitle>
        </CardHeading>
      </CardHeader>
      <CardContent className="space-y-4 p-0">
        <DataGrid table={table} recordCount={rows.length}>
          <DataGridTable />
        </DataGrid>
        {report.messagesWithInferredTimestamp > 0 && (
          <p className="text-muted-foreground px-4 pb-2 text-sm">
            {report.messagesWithInferredTimestamp} message timestamps were inferred (no source status
            timestamp).
          </p>
        )}
        {report.blockers.length > 0 && (
          <ul className="space-y-1 px-4 pb-4 text-sm">
            {report.blockers.map((b, i) => (
              <li key={i} className="flex items-start gap-2">
                <Badge variant="warning" appearance="light" size="sm" className="mt-0.5 shrink-0">
                  Blocker
                </Badge>
                <ClampedText text={b} lines={2} />
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
