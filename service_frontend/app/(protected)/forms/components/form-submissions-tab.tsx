'use client';

/** Submissions tab (plan sprint-3/01 D18) - embedded Resource list scoped to
 * THIS form: respondent (or "Anonymous"), live status segments from the
 * form's scoped graph, submitted-at, author-pinned answer columns, CSV
 * export (answers flattened; repeater = JSON cell v1), graph-driven row
 * transition actions. Row click → the read-only submission page. */
import { useEffect, useMemo, useState } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import {
  DataGridTableRowSelect,
  DataGridTableRowSelectAll,
} from '@/components/ui/data-grid-table';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import { ClampedText } from '@/components/platform/clamped-text';
import {
  ResourceList,
  type ResourceAction,
  type ResourceListConfig,
} from '@/components/platform/resource-list';
import { StatusBadge, colorToHex, colorToTone } from '@/components/platform/status-badge';
import { useDatetime } from '@/hooks/use-datetime';
import { formService, type FormSubmissionGraph } from '@/services/form-service';
import type { FormDetail, FormSubmissionRow } from '@/types/forms';
import { formPath } from './paths';

const stop = (e: React.MouseEvent) => e.stopPropagation();

function answerCell(value: unknown): string {
  if (value == null) return '';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

export interface FormSubmissionsTabProps {
  form: FormDetail;
}

export function FormSubmissionsTab({ form }: FormSubmissionsTabProps) {
  const { formatDateTime } = useDatetime();
  const [graph, setGraph] = useState<FormSubmissionGraph | null>(null);

  useEffect(() => {
    let cancelled = false;
    formService
      .submissionGraph(form.id)
      .then((g) => !cancelled && setGraph(g))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [form.id]);

  const config = useMemo<ResourceListConfig<FormSubmissionRow>>(() => {
    // Graph-driven transition actions (edge label = action text, D15): one
    // registry entry per edge label; rows qualify when the edge is fireable
    // from THEIR current status.
    const transitionActions: ResourceAction<FormSubmissionRow>[] = (graph?.transitions ?? []).map(
      (t) => ({
        id: `transition-${t.id}`,
        label: t.label,
        surfaces: { row: true },
        permission: 'submissions.manage',
        isVisible: (rows: FormSubmissionRow[]) =>
          rows.length > 0 && rows.every((s) => (s.availableTransitionIds ?? []).includes(t.id)),
        run: async (rows: FormSubmissionRow[], runtime: { reload: () => void }) => {
          for (const s of rows) await formService.transitionSubmission(s.id, t.id);
          toast.success(`${t.label} applied.`);
          runtime.reload();
        },
      }),
    );

    // Field labels (not the raw answer keys) head the pinned answer columns.
    const labelFor: Record<string, string> = {};
    for (const page of form.draftDefinition?.pages ?? []) {
      for (const section of page.sections) {
        for (const field of section.fields) {
          if (field.key) labelFor[field.key] = field.label || field.key;
        }
      }
    }

    const pinnedColumns: ColumnDef<FormSubmissionRow>[] = form.pinnedColumns.map((key) => ({
      id: `answers.${key}`,
      accessorFn: (row: FormSubmissionRow) => answerCell(row.answers[key]),
      meta: { headerTitle: labelFor[key] ?? key },
      header: ({ column }) => <DataGridColumnHeader title={labelFor[key] ?? key} column={column} />,
      cell: ({ row }) => (
        <ClampedText text={answerCell(row.original.answers[key])} lines={1} className="text-sm" />
      ),
      size: 160,
      enableSorting: false,
    }));

    const columns: ColumnDef<FormSubmissionRow>[] = [
      {
        id: 'select',
        meta: { reorderable: false },
        header: () => (
          <div onClick={stop}>
            <DataGridTableRowSelectAll />
          </div>
        ),
        cell: ({ row }) => (
          <div onClick={stop}>
            <DataGridTableRowSelect row={row} />
          </div>
        ),
        size: 48,
        enableSorting: false,
        enableHiding: false,
        enableResizing: false,
      },
      {
        id: 'respondent',
        accessorFn: (row) => row.userName ?? 'Anonymous',
        meta: { headerTitle: 'Respondent' },
        header: ({ column }) => <DataGridColumnHeader title="Respondent" column={column} />,
        cell: ({ row }) => (
          <span className="flex items-center gap-2">
            <span className="text-sm font-medium text-foreground">
              {row.original.userName ?? 'Anonymous'}
            </span>
            {row.original.revisionNumber > 1 && (
              <Badge variant="secondary" appearance="light" size="sm">
                rev {row.original.revisionNumber}
              </Badge>
            )}
          </span>
        ),
        size: 180,
        enableSorting: true,
      },
      {
        id: 'status',
        accessorFn: (row) => row.statusLabel,
        meta: { headerTitle: 'Status' },
        header: ({ column }) => <DataGridColumnHeader title="Status" column={column} />,
        cell: ({ row }) => (
          <StatusBadge
            status={row.original.statusKey}
            registry={{
              [row.original.statusKey]: {
                label: row.original.statusLabel,
                tone: colorToTone(row.original.statusColor),
                hex: colorToHex(row.original.statusColor),
              },
            }}
          />
        ),
        size: 130,
        enableSorting: false,
      },
      ...pinnedColumns,
      {
        id: 'version',
        accessorFn: (row) => row.versionNumber,
        meta: { headerTitle: 'Version' },
        header: ({ column }) => <DataGridColumnHeader title="Version" column={column} />,
        cell: ({ row }) => (
          <span className="text-xs text-muted-foreground">v{row.original.versionNumber}</span>
        ),
        size: 80,
        enableSorting: false,
      },
      {
        id: 'submittedAt',
        accessorFn: (row) => row.submittedAt,
        meta: { headerTitle: 'Submitted' },
        header: ({ column }) => <DataGridColumnHeader title="Submitted" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">
            {row.original.submittedAt ? formatDateTime(row.original.submittedAt) : '-'}
          </span>
        ),
        size: 160,
        enableSorting: true,
      },
      {
        id: 'actions',
        meta: { reorderable: false },
        header: () => null,
        cell: ({ row, table }) => {
          const meta = table.options.meta;
          return (
            <div onClick={stop} className="flex justify-end">
              <ActionMenu
                actions={transitionActions}
                rows={[row.original]}
                runtime={{ reload: meta?.reload ?? (() => {}) }}
                surface="row"
              />
            </div>
          );
        },
        size: 60,
        enableSorting: false,
        enableHiding: false,
        enableResizing: false,
      },
    ];

    return {
      viewKey: `forms.submissions.${form.id}`,
      getRowId: (row) => row.id,
      rowHref: (row) => `${formPath(form.id)}/submissions/${row.id}`,
      fetcher: (query) => formService.submissions(form.id, query),
      exporter: (query, exportColumns) =>
        formService.exportSubmissions(form.id, query, exportColumns),
      searchPlaceholder: 'Search submissions…',
      searchHints: ['Respondent', 'Answers'],
      defaultSort: { id: 'submittedAt', desc: true },
      exportFilename: `${form.slug}-submissions`,
      enableStatusViews: false,
      segments: [
        { id: 'all', label: 'All statuses' },
        ...(graph?.statuses ?? []).map((s) => ({ id: s.key, label: s.label })),
      ],
      defaultSegment: 'all',
      columns,
      filterFields: [],
      exportColumns: [
        { id: 'respondent', label: 'Respondent' },
        { id: 'statusLabel', label: 'Status' },
        { id: 'versionNumber', label: 'Version' },
        { id: 'submittedAt', label: 'Submitted' },
        ...form.pinnedColumns.map((key) => ({ id: `answers.${key}`, label: labelFor[key] ?? key })),
      ],
      actions: transitionActions,
    };
  }, [form.id, form.slug, form.pinnedColumns, form.draftDefinition, graph, formatDateTime]);

  return <ResourceList config={config} />;
}
