'use client';

/**
 * Per-entity failure table on the job detail page (AC-MIG-08) - ONE
 * `DataGrid` (mirrors `jobs/[id]/failed-assets-card.tsx`) plus a Download
 * link for the FULL failure CSV. The download is an AUTHED streaming
 * request (D-A6-23) - never a bare `<a href>` to a backend path, because
 * that would bypass the Bearer token entirely; it fetches the CSV text
 * through the service (which carries auth) and triggers a client-side Blob
 * download, the SAME convention the shell's own Export button uses
 * (`resource-list.tsx` `downloadCsv`).
 */
import { useMemo, useState } from 'react';
import { Download, LoaderCircle } from 'lucide-react';
import { type ColumnDef, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import { Card, CardContent, CardHeader, CardHeading, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { DataGrid } from '@/components/ui/data-grid';
import { DataGridTable } from '@/components/ui/data-grid-table';
import { ClampedText } from '@/components/platform/clamped-text';
import { toast } from '@/lib/toast';
import { respondioMigrationService } from '@/services/respondio-migration-service';
import type { MigrationFailureRow } from '@/types/respondio-migration';

function downloadCsv(filename: string, text: string) {
  const blob = new Blob([text], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function MigrationFailuresTable({
  jobId,
  rows,
  totalFailures,
}: {
  jobId: string;
  rows: MigrationFailureRow[];
  totalFailures: number;
}) {
  const [downloading, setDownloading] = useState(false);

  const columns = useMemo<ColumnDef<MigrationFailureRow>[]>(
    () => [
      { id: 'entity', header: 'Entity', cell: ({ row }) => <span className="font-medium">{row.original.entity}</span> },
      { id: 'sourceId', header: 'Source id', cell: ({ row }) => <span className="font-mono text-xs">{row.original.sourceId}</span> },
      { id: 'sourceLabel', header: 'Source label', cell: ({ row }) => <ClampedText text={row.original.sourceLabel} lines={1} /> },
      { id: 'reason', header: 'Reason', cell: ({ row }) => <ClampedText text={row.original.reason} lines={2} className="text-destructive" /> },
      { id: 'action', header: 'Action taken', cell: ({ row }) => <span className="text-muted-foreground">{row.original.action}</span> },
    ],
    [],
  );

  const table = useReactTable({
    data: rows,
    columns,
    getRowId: (_row, i) => String(i),
    getCoreRowModel: getCoreRowModel(),
  });

  const download = async () => {
    setDownloading(true);
    try {
      const csv = await respondioMigrationService.downloadFailuresCsv(jobId);
      downloadCsv(`migration-${jobId}-failures.csv`, csv);
    } catch {
      toast.error('Could not download the failure report. Please try again.');
    } finally {
      setDownloading(false);
    }
  };

  return (
    <Card className="mt-5">
      <CardHeader>
        <CardHeading>
          <CardTitle>Failures ({totalFailures})</CardTitle>
        </CardHeading>
        <Button type="button" variant="outline" size="sm" onClick={download} disabled={downloading}>
          {downloading ? <LoaderCircle className="size-4 animate-spin" /> : <Download className="size-4" />}
          Download CSV
        </Button>
      </CardHeader>
      <CardContent className="p-0">
        <DataGrid table={table} recordCount={rows.length}>
          <DataGridTable />
        </DataGrid>
      </CardContent>
    </Card>
  );
}
