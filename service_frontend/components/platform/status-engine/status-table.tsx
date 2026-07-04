'use client';

/**
 * Companion tabular view (sprint-2/01) — scan the statuses, drag-reorder the
 * display order (no manual sort numbers, D-UX), quick CSV export. The canvas
 * remains the graph editor; this is the list-shaped lens on the same data.
 */
import { useEffect, useState } from 'react';
import {
  DndContext,
  type DragEndEvent,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import {
  SortableContext,
  arrayMove,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { Download, GripVertical } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
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

function SortableRow({
  status,
  canManage,
  onClick,
}: {
  status: StatusNodeData;
  canManage: boolean;
  onClick: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: status.id,
  });

  return (
    // Raw <tr> (TableRow doesn't forward refs) styled to match table-row.
    <tr
      ref={setNodeRef}
      data-slot="table-row"
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={cn(
        'border-b transition-colors [&:has(td):hover]:bg-muted/50',
        isDragging ? 'relative z-10 bg-accent' : 'cursor-pointer',
      )}
      onClick={onClick}
      data-testid={`status-row-${status.key}`}
    >
      <TableCell className="w-10">
        {canManage && (
          <button
            type="button"
            className="cursor-grab text-muted-foreground"
            aria-label={`Reorder ${status.label}`}
            onClick={(e) => e.stopPropagation()}
            {...attributes}
            {...listeners}
          >
            <GripVertical className="size-4" />
          </button>
        )}
      </TableCell>
      <TableCell>
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
      </TableCell>
      <TableCell className="text-muted-foreground">{status.key}</TableCell>
      <TableCell>
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
      </TableCell>
      <TableCell className="text-end tabular-nums">{status.recordCount}</TableCell>
    </tr>
  );
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

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = rows.findIndex((r) => r.id === active.id);
    const newIndex = rows.findIndex((r) => r.id === over.id);
    const next = arrayMove(rows, oldIndex, newIndex);
    setRows(next); // optimistic — server refetch converges
    void onReorder(next.map((r) => r.id));
  };

  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex items-center justify-end">
        <Button variant="outline" size="sm" onClick={() => exportCsv(rows, entityLabel)}>
          <Download className="size-3.5" /> Export CSV
        </Button>
      </div>
      <div className="rounded-xl border border-border">
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10" />
                <TableHead>Status</TableHead>
                <TableHead>Key</TableHead>
                <TableHead>Behavior</TableHead>
                <TableHead className="text-end">Records</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <SortableContext
                items={rows.map((r) => r.id)}
                strategy={verticalListSortingStrategy}
              >
                {rows.map((status) => (
                  <SortableRow
                    key={status.id}
                    status={status}
                    canManage={canManage}
                    onClick={() => onRowClick(status)}
                  />
                ))}
              </SortableContext>
            </TableBody>
          </Table>
        </DndContext>
      </div>
    </div>
  );
}
