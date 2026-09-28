'use client';

import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Archive, ArchiveRestore, ArrowRight, FileText, GitMerge, Split, Trash2 } from 'lucide-react';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import { ClampedText } from '@/components/platform/clamped-text';
import {
  DataGridTableRowSelect,
  DataGridTableRowSelectAll,
} from '@/components/ui/data-grid-table';
import { Badge } from '@/components/ui/badge';
import { StatusBadge, colorToHex, colorToTone, type StatusRegistry } from '@/components/platform/status-badge';
import type {
  ResourceAction,
  ResourceListConfig,
} from '@/components/platform/resource-list';
import type { ListQuery, ListResult } from '@/types/resource';
import { IDEA_SOURCE_LABEL, type Idea } from '@/types/ideation';
import { toCsv } from '@/lib/csv';
import { useIdeationRuntime } from '@/hooks/use-ideation-runtime';
import { selectIdeaRows } from './select-idea-rows';
import { VoteCell } from './components/vote-cell';

const stop = (e: React.MouseEvent) => e.stopPropagation();

function statusRegistryFor(idea: Idea): StatusRegistry<string> {
  const label = idea.statusLabel ?? idea.status;
  return {
    [idea.status]: {
      label,
      tone: colorToTone(idea.statusColor),
      hex: colorToHex(idea.statusColor),
    },
  };
}

/** "Move to {label}" when every selected row's advance target agrees, else the
 * generic verb (AC-94-57) - never a hardcoded key. */
function advanceLabel(rows: Idea[]): string {
  const labels = Array.from(
    new Set(rows.map((r) => r.transitions?.find((t) => t.id === r.advanceTransitionId)?.toStatusLabel)),
  );
  const only = labels[0];
  return labels.length === 1 && only ? `Move to ${only}` : 'Advance to next stage';
}

/**
 * Ideas list config (plan Phase A, grown by issue #94 "ideation round 2") on
 * the shared ResourceList - SAME component as the Users list. Row order IS
 * the server's rank order (top = highest priority, AC-94-47); reordered via
 * the left grip (config.rowReorder). Column sorting is disabled so the drag
 * order stays meaningful. Row-click opens the idea form; votes are a per-user
 * toggle; status/transitions come from the statuses engine, never a hardcoded
 * union (AC-94-49..57).
 */
export function useIdeasListConfig(
  ideas: Idea[],
  handlers: {
    onCreate: () => void;
    onVote: (idea: Idea, dir: 'up' | 'down') => void;
    onAdvance: (idea: Idea) => Promise<void>;
    onRestore: (idea: Idea) => Promise<void>;
    /** No longer called by this config (fix round 1, T5, item 15 - Delete is
     * `deferred`). Kept in the signature so the caller needs no change. */
    onDelete: (idea: Idea) => Promise<void>;
    onReorder: (orderedIds: string[]) => void | Promise<void>;
    onPromote: (ideas: Idea[]) => Promise<void>;
    /** Opens the survivor-picker dialog (issue #94, AC-94-21/22). */
    onMerge: (ideas: Idea[]) => void;
    /** Restores one merged idea; the caller awaits + reloads per row. */
    onUnmerge: (id: string) => Promise<void>;
  },
  opts?: { includeTest?: boolean },
): ResourceListConfig<Idea> {
  const { onCreate, onVote, onAdvance, onRestore, onReorder, onPromote, onMerge, onUnmerge } = handlers;
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
        // (foolproof-UI - never offer a move that will 422). Issue #90 W3
        // (owner ruling 26 Sep ~12:50Z): a test idea may promote to a TEST BR,
        // so an all-test selection stays enabled - only a MIXED test+real
        // selection is disabled (a promote lane cannot be mixed, same
        // principle as the mixed-product rule).
        isVisible: (rows) => rows.length > 0 && rows.every((r) => !r.statusIsArchived),
        isDisabled: (rows) =>
          new Set(rows.map((r) => r.productId)).size > 1 ||
          (rows.some((r) => r.isTest) && rows.some((r) => !r.isTest)),
        run: async (rows) => {
          await onPromote(rows);
        },
      },
      {
        id: 'merge',
        label: 'Merge',
        icon: GitMerge,
        // The embed has no session to gate against (the token IS the
        // boundary there, same as today's Advance/Archive) - only the
        // operator surface asks `useCan`.
        permission: mode === 'operator' ? 'ideation.triage.manage' : undefined,
        surfaces: { row: false, form: false, bulk: true },
        isVisible: (rows) => rows.length >= 2 && rows.every((r) => !r.statusIsArchived),
        isDisabled: (rows) =>
          new Set(rows.map((r) => r.productId)).size > 1 ||
          (rows.some((r) => r.isTest) && rows.some((r) => !r.isTest)),
        run: async (rows) => {
          onMerge(rows);
        },
      },
      {
        id: 'unmerge',
        label: 'Unmerge',
        icon: Split,
        permission: mode === 'operator' ? 'ideation.triage.manage' : undefined,
        surfaces: { row: true, form: false, bulk: true },
        isVisible: (rows) => rows.length > 0 && rows.every((r) => (r.mergedCount ?? 0) > 0),
        run: async (rows) => {
          for (const r of rows) await onUnmerge(r.id);
        },
      },
      {
        id: 'advance',
        // Label auto-derived from the fireable transition target
        // (status_engine, AC-94-57) - single row -> "Move to Triaged"; mixed
        // bulk -> generic.
        label: (rows) => advanceLabel(rows),
        icon: ArrowRight,
        surfaces: { row: true, form: true, bulk: true },
        // Hidden once archived; disabled with no fireable advance edge.
        isVisible: (rows) => rows.every((r) => !r.statusIsArchived),
        isDisabled: (rows) => rows.some((r) => !r.advanceTransitionId),
        run: async (rows) => {
          for (const r of rows) await onAdvance(r);
        },
      },
      {
        id: 'archive',
        label: 'Archive',
        icon: Archive,
        surfaces: { row: true, form: true, bulk: true },
        isVisible: (rows) => rows.every((r) => !r.statusIsArchived),
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
        isVisible: (rows) => rows.every((r) => r.statusIsArchived),
        isDisabled: (rows) => rows.some((r) => !r.transitions?.length),
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
      enableSorting: false, // order = server rank (drag); no column sort
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
      col('problem', 'Idea', ({ row }) => (
        <div className="flex items-start gap-1.5">
          <div className="min-w-0 flex-1">
            <ClampedText text={row.original.title ?? row.original.problem} lines={2} />
          </div>
          {row.original.isTest && (
            <Badge variant="secondary" appearance="light" size="sm" className="shrink-0">
              TEST
            </Badge>
          )}
          {(row.original.mergedCount ?? 0) > 0 && (
            <Badge variant="outline" appearance="light" size="sm" className="shrink-0">
              {row.original.mergedCount} merged
            </Badge>
          )}
        </div>
      ), 340),
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
        <StatusBadge status={row.original.status} registry={statusRegistryFor(row.original)} />
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
      const rows = selectIdeaRows(ideas, query);
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
          r.statusLabel ?? r.status,
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
      rowHref: (row) => paths.formHref(row.id, { includeTest: opts?.includeTest }),
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
  }, [ideas, onCreate, onVote, onAdvance, onRestore, onReorder, onPromote, onMerge, onUnmerge, paths, mode, opts?.includeTest]);
}
