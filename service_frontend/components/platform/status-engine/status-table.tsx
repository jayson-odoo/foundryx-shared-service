'use client';

/**
 * Companion tabular view (sprint-2/01) - scan the statuses, drag-reorder the
 * display order (no manual sort numbers, D-UX), quick CSV export. The canvas
 * remains the graph editor; this is the list-shaped lens on the same data.
 *
 * AC-DLA-56 (T7): migrated off the raw `@/components/ui/table` primitive onto
 * `DataGrid` + `DataGridTableDndRows` (the shared drag-reorder body,
 * `components/platform/resource-list/resource-list.tsx`'s own `rowReorder`
 * mode uses the same primitive) - sticky header + resizable + movable
 * columns come free from `DataGrid`'s own defaults (AC-DLA-13), no override
 * needed. Not on the full `ResourceList` shell: this is an in-memory,
 * unpaginated, single-entity list with no search/filter of its own.
 */
import { useEffect, useMemo, useState } from 'react';
import { type ColumnDef, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import type { DragEndEvent } from '@dnd-kit/core';
import { arrayMove } from '@dnd-kit/sortable';
import { Download } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardTable } from '@/components/ui/card';
import { DataGrid } from '@/components/ui/data-grid';
import { DataGridTableDndRowHandle, DataGridTableDndRows } from '@/components/ui/data-grid-table-dnd-rows';
import { StatusBadge, colorToHex, colorToTone } from '@/components/platform/status-badge';
import type { StatusNodeData } from '@/types/status-engine';

export interface StatusTableProps {
  statuses: StatusNodeData[];
  canManage: boolean;
  entityLabel: string;
  onReorder: (orderedIds: string[]) => Promise<boolean>;
  onRowClick: (status: StatusNodeData) => void;
}

function flagSummary(status: StatusNodeData): string[] {
  const flags: string[] = [];
  if (status.isInitial) flags.push('Initial');
  if (status.isDefault) flags.push('Default');
  if (status.isTerminal) flags.push('Terminal');
  if (status.blocksAccess) flags.push('Blocks access');
  if (status.isArchived) flags.push('Archived');
  return flags;
}

function exportCsv(statuses: StatusNodeData[], entityLabel: string) {
  const header = ['Label', 'Key', 'Color', 'Flags', 'Records', 'System'];
  const rows = statuses.map((s) => [
    s.label,
    s.key,
    s.color,
    flagSummary(s).join('; '),
    String(s.recordCount),
    s.isSystem ? 'yes' : 'no',
  ]);
  const csv = [header, ...rows]
    .map((row) => row.map((cell) => `"${cell.replaceAll('"', '""')}"`).join(','))
    .join('\n');
  const link = document.createElement('a');
  link.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
  link.download = `${entityLabel.toLowerCase()}-statuses.csv`;
  link.click();
  URL.revokeObjectURL(link.href);
}

export function StatusTable({
  statuses,
  canManage,
  entityLabel,
  onReorder,
  onRowClick,
}: StatusTableProps) {
  const [rows, setRows] = useState(statuses);
  useEffect(() => setRows(statuses), [statuses]);

  const columns = useMemo<ColumnDef<StatusNodeData>[]>(
    () => [
      {
        id: 'drag',
        header: () => null,
        cell: ({ row }) =>
          canManage ? (
            <DataGridTableDndRowHandle
              rowId={row.id}
              ariaLabel={`Reorder ${row.original.label}`}
            />
          ) : null,
        size: 44,
        enableSorting: false,
        enableResizing: false,
        enableHiding: false,
        meta: { reorderable: false, utility: true },
      },
      {
        id: 'status',
        header: 'Status',
        cell: ({ row }) => {
          const status = row.original;
          return (
            <StatusBadge
              status={status.key}
              registry={{
                [status.key]: {
                  label: status.label,
                  tone: colorToTone(status.color),
                  hex: colorToHex(status.color),
                },
              }}
            />
          );
        },
      },
      {
        id: 'key',
        header: 'Key',
        accessorKey: 'key',
        cell: ({ row }) => <span className="text-muted-foreground">{row.original.key}</span>,
      },
      {
        id: 'behavior',
        header: 'Behavior',
        cell: ({ row }) => {
          const status = row.original;
          return (
            <div className="flex flex-wrap gap-1">
              {flagSummary(status).map((flag) => (
                <Badge key={flag} variant="secondary" appearance="light" size="sm">
                  {flag}
                </Badge>
              ))}
              {!status.isActive && (
                <Badge variant="destructive" appearance="light" size="sm">
                  Inactive
                </Badge>
              )}
            </div>
          );
        },
      },
      {
        id: 'records',
        header: 'Records',
        accessorKey: 'recordCount',
        meta: { headerClassName: 'text-end', cellClassName: 'text-end tabular-nums' },
      },
    ],
    [canManage],
  );

  const table = useReactTable({
    data: rows,
    columns,
    getRowId: (row) => row.id,
    getCoreRowModel: getCoreRowModel(),
  });

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = rows.findIndex((r) => r.id === active.id);
    const newIndex = rows.findIndex((r) => r.id === over.id);
    const next = arrayMove(rows, oldIndex, newIndex);
    setRows(next); // optimistic - server refetch converges
    void onReorder(next.map((r) => r.id));
  };

  return (
    <DataGrid table={table} recordCount={rows.length} onRowClick={onRowClick}>
      <div className="flex flex-col gap-2.5">
        <div className="flex items-center justify-end">
          <Button variant="outline" size="sm" onClick={() => exportCsv(rows, entityLabel)}>
            <Download className="size-3.5" /> Export CSV
          </Button>
        </div>
        <Card>
          <CardTable>
            <DataGridTableDndRows handleDragEnd={handleDragEnd} dataIds={rows.map((r) => r.id)} />
          </CardTable>
        </Card>
      </div>
    </DataGrid>
  );
}
