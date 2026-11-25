'use client';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { useMemo } from 'react';
import { type ColumnDef, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import { DataGrid } from '@/components/ui/data-grid';
import { DataGridTable } from '@/components/ui/data-grid-table';
import type { DocFeedMonthCounts, DocFeedRun } from '@/types/autocount';
import { docFeedLabel } from '../../components/autocount-meta';

export interface DocFeedMonthCountsDialogProps {
  run: DocFeedRun;
  onClose: () => void;
}

type CountKey = keyof DocFeedMonthCounts;

const COLUMNS: Array<{ key: CountKey; label: string }> = [
  { key: 'read', label: 'Read' },
  { key: 'created', label: 'Created' },
  { key: 'updated', label: 'Updated' },
  { key: 'unchanged', label: 'Unchanged' },
  { key: 'needsReview', label: 'Needs review' },
  { key: 'skipped', label: 'Skipped' },
];

/** `YYYY-MM` -> `mm/yyyy` (the house dd/mm/yyyy order, month only). */
export function monthLabel(month: string): string {
  const [year, mm] = month.split('-');
  return year && mm ? `${mm}/${year}` : month;
}

/** The months of a run's `byMonth`, oldest first. */
export function monthRows(run: DocFeedRun): Array<[string, DocFeedMonthCounts]> {
  const byMonth = run.summary?.byMonth ?? {};
  return Object.entries(byMonth).sort(([a], [b]) => a.localeCompare(b));
}

/**
 * Plan 72 (UAC S0-10) - a backfill run's records and CRM answers by month,
 * read from the run's own summary, so the dry-run pass can be checked before
 * the real pass.
 */
interface MonthRow extends DocFeedMonthCounts {
  /** `YYYY-MM`, or `total` for the last row. */
  id: string;
  label: string;
}

/** The popup's rows: one per month, oldest first, then the total. */
export function monthTableRows(run: DocFeedRun): MonthRow[] {
  const rows: MonthRow[] = monthRows(run).map(([month, counts]) => ({
    ...counts,
    id: month,
    label: monthLabel(month),
  }));
  const total: MonthRow = { id: 'total', label: 'Total' };
  for (const c of COLUMNS) {
    total[c.key] = rows.reduce((sum, row) => sum + (row[c.key] ?? 0), 0);
  }
  return [...rows, total];
}

export function DocFeedMonthCountsDialog({ run, onClose }: DocFeedMonthCountsDialogProps) {
  const data = useMemo(() => monthTableRows(run), [run]);
  const columns = useMemo<ColumnDef<MonthRow>[]>(
    () => [
      {
        id: 'month',
        header: 'Month',
        cell: ({ row }) => (
          <span className={row.original.id === 'total' ? 'font-medium' : undefined}>{row.original.label}</span>
        ),
        size: 100,
      },
      ...COLUMNS.map<ColumnDef<MonthRow>>((c) => ({
        id: c.key,
        header: c.label,
        cell: ({ row }) => (
          <span className="tabular-nums" data-testid={`doc-feed-month-${row.original.id}-${c.key}`}>
            {row.original[c.key] ?? 0}
          </span>
        ),
        size: 115,
      })),
    ],
    [],
  );
  const table = useReactTable({ data, columns, getRowId: (r) => r.id, getCoreRowModel: getCoreRowModel() });

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle>Counts by month - {docFeedLabel(run.feed)}</DialogTitle>
          <DialogDescription className="sr-only">Counts by month</DialogDescription>
        </DialogHeader>
        <DialogBody>
          <div className="max-h-[60vh] overflow-auto" data-testid="doc-feed-month-counts">
            <DataGrid table={table} recordCount={data.length}>
              <DataGridTable />
            </DataGrid>
          </div>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
