'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { toast } from '@/lib/toast';
import { ChevronDown, ChevronUp, GripVertical } from 'lucide-react';
import {
  Kanban,
  KanbanBoard,
  KanbanColumn,
  KanbanColumnContent,
  KanbanItem,
  KanbanItemHandle,
  KanbanOverlay,
  type KanbanMoveEvent,
} from '@/components/ui/kanban';
import { Badge } from '@/components/ui/badge';
import { useIdeas } from '@/hooks/use-ideas';
import { useIdeationRuntime } from '@/hooks/use-ideation-runtime';
import { IDEA_SOURCE_LABEL, type BoardColumn, type Idea } from '@/types/ideation';

type Columns = Record<string, Idea[]>;

/**
 * Fallback column derivation (issue #94, ideation round 2) for a caller whose
 * `useIdeas()` doesn't (yet) surface `columns` (e.g. an older test double) -
 * groups by each idea's OWN engine-resolved status (never a hardcoded FE
 * union, AC-94-58), so an idea with no `statusId` at all (a bare fixture)
 * still lands somewhere rather than vanishing from the board.
 */
function columnsFromIdeas(ideas: Idea[]): BoardColumn[] {
  const seen = new Map<string, BoardColumn>();
  for (const idea of ideas) {
    if (idea.statusIsArchived || idea.mergedIntoId) continue;
    const statusId = idea.statusId ?? idea.status;
    if (!seen.has(statusId)) {
      seen.set(statusId, {
        statusId,
        key: idea.status,
        title: idea.statusLabel ?? idea.status,
        color: idea.statusColor ?? 'gray',
        ideas: [],
      });
    }
  }
  return Array.from(seen.values());
}

function buildColumns(source: BoardColumn[], ideas: Idea[]): Columns {
  const cols: Columns = {};
  for (const c of source) cols[c.statusId] = [];
  // Within-column order = rank (ascending, falling back to priority) - so
  // dragging reorders priority (AC-94-58).
  const byId = new Map(ideas.map((i) => [i.id, i]));
  for (const c of source) {
    const rows = (c.ideas.length > 0 ? c.ideas : ideas.filter((i) => (i.statusId ?? i.status) === c.statusId))
      .map((i) => byId.get(i.id) ?? i)
      .sort((a, b) => a.priority - b.priority);
    cols[c.statusId] = rows;
  }
  return cols;
}

function flatten(source: BoardColumn[], cols: Columns): string[] {
  return source.flatMap((c) => (cols[c.statusId] ?? []).map((i) => i.id));
}

/**
 * A cross-column drop is valid only when the dragged idea's OWN fireable
 * transitions (status_engine, `always=True`) reach the target column's status
 * (AC-94-58) - exported so the rule is unit-testable without simulating a
 * full drag-and-drop gesture in jsdom.
 */
export function canMoveTo(idea: Idea | undefined, targetStatusId: string): boolean {
  return Boolean(idea?.transitions?.some((t) => t.toStatusId === targetStatusId));
}

function IdeaCardBody({ idea, ghost }: { idea: Idea; ghost?: boolean }) {
  const score = idea.upvotes - idea.downvotes;
  return (
    <div
      className={
        'rounded-lg border bg-card p-3 ' + (ghost ? 'shadow-lg ring-2 ring-primary' : 'shadow-xs')
      }
    >
      <div className="flex items-start gap-1.5">
        <GripVertical className="mt-0.5 size-4 shrink-0 text-muted-foreground/60" />
        <p className="text-sm font-medium leading-snug">{idea.title ?? idea.problem}</p>
      </div>
      <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5 ps-5">
        <Badge variant="secondary" className="truncate">
          {idea.productName}
        </Badge>
        {idea.isTest && (
          <Badge variant="secondary" appearance="light" size="sm">
            TEST
          </Badge>
        )}
        {(idea.mergedCount ?? 0) > 0 && (
          <Badge variant="outline" appearance="light" size="sm">
            {idea.mergedCount} merged
          </Badge>
        )}
        <span className="inline-flex items-center gap-2 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-0.5">
            <ChevronUp className="size-3.5 text-emerald-600" />
            {idea.upvotes}
          </span>
          <span className="inline-flex items-center gap-0.5">
            <ChevronDown className="size-3.5 text-rose-500" />
            {idea.downvotes}
          </span>
          <span className="tabular-nums font-medium text-foreground">{score}</span>
        </span>
      </div>
      <p className="mt-2 ps-5 text-xs text-muted-foreground">
        {idea.submitterName} · {IDEA_SOURCE_LABEL[idea.source]}
        {idea.submitterTier && <> · {idea.submitterTier}</>}
      </p>
    </div>
  );
}

/**
 * The triage Kanban board - the SINGLE board component used by BOTH the operator
 * page and the chrome-less host iframe (WS-C1 / AC-CAP-9). Columns come from
 * the statuses engine (`useIdeas()`'s `columns`, AC-94-58), never a hardcoded
 * FE list; a drop is only honoured when the card's own `transitions` reach
 * that column's status (AC-94-58) - an invalid drop is refused and the board
 * reverts. Drag within a column reorders priority. The backend + card URLs
 * come from `useIdeationRuntime()` (operator default or embed).
 */
export function TriageBoard() {
  // `withBoard` (AC-94-58) - the board is the ONLY caller that needs the
  // extra `getBoard` request; the list and the form never pay for it.
  const { ideas, columns: apiColumns, loading, error, setStatus, reorderPriority, reload } = useIdeas({
    withBoard: true,
  });
  const { paths } = useIdeationRuntime();

  const source = useMemo<BoardColumn[]>(
    () => (apiColumns && apiColumns.length > 0 ? apiColumns : columnsFromIdeas(ideas)),
    [apiColumns, ideas],
  );

  // Seeded from `source`/`ideas` at mount (never an empty `{}`) - the Kanban
  // primitive reads every column's key on first render, so a column with no
  // entry yet would crash before the sync-up effect below ever runs.
  const [columns, setColumns] = useState<Columns>(() => buildColumns(source, ideas));
  const latest = useRef<Columns>(columns);

  useEffect(() => {
    const next = buildColumns(source, ideas);
    setColumns(next);
    latest.current = next;
  }, [source, ideas]);

  const onChange = (next: Columns) => {
    setColumns(next);
    latest.current = next;
  };

  const handleMove = async (e: KanbanMoveEvent) => {
    const id = String(e.event.active.id);
    const order = flatten(source, latest.current); // reflects the drop position
    try {
      if (e.activeContainer !== e.overContainer) {
        const idea = ideas.find((i) => i.id === id);
        // Drop is only valid when this card's own fireable transitions reach
        // the target column's status (AC-94-58) - foolproof-UI, never a move
        // the backend would 409 on.
        if (!canMoveTo(idea, e.overContainer)) {
          toast.error('That move is not allowed from this stage.');
          setColumns(buildColumns(source, ideas)); // revert the optimistic drag
          return;
        }
        await setStatus(id, e.overContainer);
      }
      await reorderPriority(order); // board reading order → priority
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not move the idea.');
      void reload(); // revert optimistic drag from the source of truth
    }
  };

  const byId = new Map(ideas.map((i) => [i.id, i]));

  if (error && ideas.length === 0) return <p className="text-sm text-destructive">{error}</p>;
  if (loading && ideas.length === 0)
    return <p className="text-sm text-muted-foreground">Loading board…</p>;

  return (
    <Kanban value={columns} onValueChange={onChange} getItemValue={(i) => i.id} onMove={handleMove}>
      <KanbanBoard className="!flex !grid-cols-none flex-nowrap gap-4 overflow-x-auto pb-3">
        {source.map((col) => (
          <KanbanColumn key={col.statusId} value={col.statusId} className="w-80 shrink-0 rounded-lg bg-muted/40 p-3">
            <div className="flex items-center justify-between px-1 pb-2">
              <span className="text-sm font-semibold">{col.title}</span>
              <Badge variant="outline">{columns[col.statusId]?.length ?? 0}</Badge>
            </div>
            <KanbanColumnContent value={col.statusId} className="min-h-16">
              {(columns[col.statusId] ?? []).map((idea) => (
                <KanbanItem key={idea.id} value={idea.id}>
                  <KanbanItemHandle asChild>
                    <Link href={paths.formHref(idea.id)} draggable={false}>
                      <IdeaCardBody idea={idea} />
                    </Link>
                  </KanbanItemHandle>
                </KanbanItem>
              ))}
              {(columns[col.statusId]?.length ?? 0) === 0 && (
                <p className="px-1 py-6 text-center text-xs text-muted-foreground">Drop ideas here</p>
              )}
            </KanbanColumnContent>
          </KanbanColumn>
        ))}
      </KanbanBoard>
      <KanbanOverlay>
        {({ value }) => {
          const idea = byId.get(String(value));
          return idea ? <IdeaCardBody idea={idea} ghost /> : null;
        }}
      </KanbanOverlay>
    </Kanban>
  );
}
