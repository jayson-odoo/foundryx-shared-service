'use client';

import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Archive, ArchiveRestore, ArrowRight, ChevronDown, ChevronUp, FileText, Trash2 } from 'lucide-react';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import { ClampedText } from '@/components/platform/clamped-text';
import {
  DataGridTableRowSelect,
  DataGridTableRowSelectAll,
} from '@/components/ui/data-grid-table';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import type {
  ResourceAction,
  ResourceListConfig,
} from '@/components/platform/resource-list';
import type { ListQuery, ListResult } from '@/types/resource';
import {
  IDEA_NEXT_STATUS,
  IDEA_SOURCE_LABEL,
  IDEA_STATUS_LABEL,
  type Idea,
} from '@/types/ideation';
import { toCsv } from '@/lib/csv';
import { useIdeationRuntime } from '@/hooks/use-ideation-runtime';

const stop = (e: React.MouseEvent) => e.stopPropagation();

function VoteCell({ idea, onVote }: { idea: Idea; onVote: (idea: Idea, dir: 'up' | 'down') => void }) {
  return (
    <div onClick={stop} className="flex items-center gap-1">
      <button
        type="button"
        aria-label={idea.myVote === 'up' ? 'Cancel upvote' : 'Upvote'}
        aria-pressed={idea.myVote === 'up'}
        onClick={() => onVote(idea, 'up')}
        className={cn(
          PRESSED_CLASS,
          'inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-sm transition-colors',
          idea.myVote === 'up'
            ? 'bg-emerald-50 font-medium text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400'
            : 'text-muted-foreground hover:bg-muted',
        )}
      >
        <ChevronUp className="size-4" />
        {idea.upvotes}
      </button>
      <button
        type="button"
        aria-label={idea.myVote === 'down' ? 'Cancel downvote' : 'Downvote'}
        aria-pressed={idea.myVote === 'down'}
        onClick={() => onVote(idea, 'down')}
        className={cn(
          PRESSED_CLASS,
          'inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-sm transition-colors',
          idea.myVote === 'down'
            ? 'bg-rose-50 font-medium text-rose-700 dark:bg-rose-950/40 dark:text-rose-400'
            : 'text-muted-foreground hover:bg-muted',
        )}
      >
        <ChevronDown className="size-4" />
        {idea.downvotes}
      </button>
    </div>
  );
}

/**
 * Ideas list config (plan Phase A) on the shared ResourceList - SAME component
 * as the Users list. Row order IS priority (top = highest), reordered via the
 * left grip (config.rowReorder). Column sorting is disabled so the drag order
 * stays meaningful. Row-click opens the idea form; votes are a per-user toggle.
 *
 * Actions (row + form + bulk): Advance to next stage (status_engine transition -
 * prototype uses IDEA_NEXT_STATUS), Archive/Restore (soft, via the Active |
 * Archived status view), and hard Delete. Bulk-select via the select column.
 */
export function useIdeasListConfig(
  ideas: Idea[],
  handlers: {
    onCreate: () => void;
    onVote: (idea: Idea, dir: 'up' | 'down') => void;
    onAdvance: (idea: Idea) => Promise<void>;
    /** No longer called by this config (fix round 1, T5, item 15 - Archive is
     * `deferred`, the registered handler commits it server-side). Kept in
     * the signature so the caller needs no change. */
    onArchive: (idea: Idea) => Promise<void>;
    onRestore: (idea: Idea) => Promise<void>;
    /** No longer called by this config (fix round 1, T5, item 15 - Delete is
     * `deferred`). Kept in the signature so the caller needs no change. */
    onDelete: (idea: Idea) => Promise<void>;
    onReorder: (orderedIds: string[]) => void | Promise<void>;
    onPromote: (ideas: Idea[]) => Promise<void>;
  },
): ResourceListConfig<Idea> {
  const { onCreate, onVote, onAdvance, onRestore, onReorder, onPromote } = handlers;
  const { paths, mode } = useIdeationRuntime();

  return useMemo<ResourceListConfig<Idea>>(() => {
    const actions: ResourceAction<Idea>[] = [
      {
        id: 'promote-br',
        label: 'Promote to BR',
        icon: FileText,
        // Gated by the BR write perm - the destination is a new draft BR.
        permission: 'ideation.business_requirements.manage',
        surfaces: { row: true, form: true, bulk: true },
        // Only non-archived ideas that all share ONE product (a BR links
        // same-product ideas, AC-BI-17). A mixed-product selection is disabled
        // (foolproof-UI - never offer a move that will 422).
        isVisible: (rows) => rows.length > 0 && rows.every((r) => r.status !== 'archived'),
        isDisabled: (rows) => new Set(rows.map((r) => r.productId)).size > 1,
        run: async (rows) => {
          await onPromote(rows);
        },
      },
      {
        id: 'advance',
        // Label auto-derived from the status_engine transition target (prototype:
        // IDEA_NEXT_STATUS). Single row → "Move to Triaged"; mixed bulk → generic.
        label: (rows) => {
          const nexts = Array.from(new Set(rows.map((r) => IDEA_NEXT_STATUS[r.status])));
          const next = nexts.length === 1 ? nexts[0] : undefined;
          return next ? `Move to ${IDEA_STATUS_LABEL[next]}` : 'Advance to next stage';
        },
        icon: ArrowRight,
        surfaces: { row: true, form: true, bulk: true },
        // Hidden once archived; disabled at a terminal stage (no next state).
        isVisible: (rows) => rows.every((r) => r.status !== 'archived'),
        isDisabled: (rows) => rows.some((r) => !IDEA_NEXT_STATUS[r.status]),
        run: async (rows) => {
          for (const r of rows) await onAdvance(r);
        },
      },
      {
        id: 'archive',
        label: 'Archive',
        icon: Archive,
        surfaces: { row: true, form: true, bulk: true },
        isVisible: (rows) => rows.every((r) => r.status !== 'archived'),
        // Grace-window deferred action (sprint-4/23, T5 fix round 1, item
        // 15) - no confirm, no `run` (the registered `ideation_ideas.archive`
        // handler commits it server-side; Restore stays a plain, un-gated
        // action, so this is the reversible window).
        deferred: { actionKey: 'ideation_ideas.archive', entityType: 'ideation_idea' },
      },
      {
        id: 'restore',
        label: 'Restore',
        icon: ArchiveRestore,
        surfaces: { row: true, form: true, bulk: true },
        isVisible: (rows) => rows.every((r) => r.status === 'archived'),
        run: async (rows) => {
          for (const r of rows) await onRestore(r);
        },
      },
      {
        id: 'delete',
        label: 'Delete',
        icon: Trash2,
        tone: 'destructive',
        surfaces: { row: true, form: true, bulk: true },
        // Grace-window deferred action - no confirm, no `run` (the
        // registered `ideation_ideas.delete` handler commits it
        // server-side).
        deferred: { actionKey: 'ideation_ideas.delete', entityType: 'ideation_idea' },
      },
    ];

    const col = (id: string, title: string, cell: ColumnDef<Idea>['cell'], size: number): ColumnDef<Idea> => ({
      id,
      header: () => title,
      cell,
      size,
      enableSorting: false, // order = priority (drag); no column sort
    });

    const columns: ColumnDef<Idea>[] = [
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
      col('problem', 'Idea', ({ row }) => <ClampedText text={row.original.problem} lines={2} />, 340),
      col('submitter', 'Submitter', ({ row }) => (
        <span className="text-muted-foreground">{row.original.submitterName}</span>
      ), 130),
      col('channel', 'Channel', ({ row }) => (
        <Badge variant="outline" appearance="light">{IDEA_SOURCE_LABEL[row.original.source]}</Badge>
      ), 110),
      col('product', 'Product', ({ row }) => (
        <Badge variant="secondary">{row.original.productName}</Badge>
      ), 140),
      col('status', 'Status', ({ row }) => (
        <Badge variant="outline">{IDEA_STATUS_LABEL[row.original.status]}</Badge>
      ), 120),
      col('votes', 'Votes', ({ row }) => <VoteCell idea={row.original} onVote={onVote} />, 130),
      {
        id: 'actions',
        meta: { reorderable: false },
        header: () => null,
        cell: ({ row, table }) => (
          <div onClick={stop} className="flex justify-end">
            <ActionMenu
              actions={actions}
              rows={[row.original]}
              runtime={{ reload: table.options.meta?.reload ?? (() => {}) }}
              surface="row"
            />
          </div>
        ),
        size: 56,
        enableSorting: false,
        enableHiding: false,
        enableResizing: false,
      },
    ];

    const fetcher = async (query: ListQuery): Promise<ListResult<Idea>> => {
      const archivedView = query.statusView === 'trashed';
      let rows = [...ideas]
        .filter((r) => (archivedView ? r.status === 'archived' : r.status !== 'archived'))
        .sort((a, b) => a.priority - b.priority);
      if (query.search) {
        const s = query.search.toLowerCase();
        rows = rows.filter(
          (r) =>
            r.problem.toLowerCase().includes(s) ||
            r.submitterName.toLowerCase().includes(s) ||
            r.productName.toLowerCase().includes(s),
        );
      }
      const total = rows.length;
      const start = query.page * query.pageSize;
      return { data: rows.slice(start, start + query.pageSize), total, page: query.page };
    };

    const exporter = async (query: ListQuery): Promise<string> => {
      const { data } = await fetcher({ ...query, page: 0, pageSize: 10_000 });
      return toCsv(
        ['Idea', 'Submitter', 'Channel', 'Product', 'Status', 'Up', 'Down'],
        data.map((r) => [
          r.problem,
          r.submitterName,
          IDEA_SOURCE_LABEL[r.source],
          r.productName,
          IDEA_STATUS_LABEL[r.status],
          String(r.upvotes),
          String(r.downvotes),
        ]),
      );
    };

    return {
      // Operator personalises columns per view; the embed iframe has no operator
      // user, so it uses a distinct key (its best-effort save 401s harmlessly).
      viewKey: mode === 'embed' ? 'ideation.ideas.embed' : 'ideation.ideas',
      getRowId: (row) => row.id,
      rowReorder: { onReorder },
      rowHref: (row) => paths.formHref(row.id),
      fetcher,
      exporter,
      searchPlaceholder: 'Search ideas…',
      searchHints: ['Idea', 'Submitter', 'Product'],
      enableStatusViews: true,
      statusViewLabels: { active: 'Active', trashed: 'Archived' },
      createLabel: 'Capture idea',
      onCreate,
      columns,
      filterFields: [],
      exportColumns: [
        { id: 'problem', label: 'Idea' },
        { id: 'submitter', label: 'Submitter' },
        { id: 'status', label: 'Status' },
      ],
      actions,
    };
  }, [ideas, onCreate, onVote, onAdvance, onRestore, onReorder, onPromote, paths, mode]);
}
