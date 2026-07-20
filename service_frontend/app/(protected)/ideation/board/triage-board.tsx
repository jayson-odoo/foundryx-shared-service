'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { toast } from 'sonner';
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
import {
  IDEA_BOARD_COLUMNS,
  IDEA_SOURCE_LABEL,
  type Idea,
  type IdeaStatus,
} from '@/types/ideation';

type Columns = Record<string, Idea[]>;

function buildColumns(ideas: Idea[]): Columns {
  const cols: Columns = {};
  for (const { key } of IDEA_BOARD_COLUMNS) cols[key] = [];
  // Within-column order = priority (ascending), so dragging reorders priority.
  for (const idea of [...ideas].sort((a, b) => a.priority - b.priority)) {
    if (cols[idea.status]) cols[idea.status].push(idea);
  }
  return cols;
}

/** Board reading order (columns L→R, cards top→bottom) = the global priority order. */
function flatten(cols: Columns): string[] {
  return IDEA_BOARD_COLUMNS.flatMap(({ key }) => (cols[key] ?? []).map((i) => i.id));
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
        <p className="text-sm font-medium leading-snug">{idea.problem}</p>
      </div>
      <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5 ps-5">
        <Badge variant="secondary" className="truncate">
          {idea.productName}
        </Badge>
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
      </p>
    </div>
  );
}

/**
 * The triage Kanban board — the SINGLE board component used by BOTH the operator
 * page and the chrome-less host iframe (WS-C1 / AC-CAP-9). Drag across columns →
 * status change; drag within a column → reorder priority. The backend + card
 * URLs come from `useIdeationRuntime()` (operator default or embed).
 */
export function TriageBoard() {
  const { ideas, loading, error, setStatus, reorderPriority, reload } = useIdeas();
  const { paths } = useIdeationRuntime();
  const [columns, setColumns] = useState<Columns>(() => buildColumns([]));
  const latest = useRef<Columns>(columns);

  useEffect(() => {
    const next = buildColumns(ideas);
    setColumns(next);
    latest.current = next;
  }, [ideas]);

  const onChange = (next: Columns) => {
    setColumns(next);
    latest.current = next;
  };

  const handleMove = async (e: KanbanMoveEvent) => {
    const id = String(e.event.active.id);
    const order = flatten(latest.current); // reflects the drop position
    try {
      if (e.activeContainer !== e.overContainer) {
        await setStatus(id, e.overContainer as IdeaStatus);
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
        {IDEA_BOARD_COLUMNS.map(({ key, title }) => (
          <KanbanColumn key={key} value={key} className="w-80 shrink-0 rounded-lg bg-muted/40 p-3">
            <div className="flex items-center justify-between px-1 pb-2">
              <span className="text-sm font-semibold">{title}</span>
              <Badge variant="outline">{columns[key]?.length ?? 0}</Badge>
            </div>
            <KanbanColumnContent value={key} className="min-h-16">
              {(columns[key] ?? []).map((idea) => (
                <KanbanItem key={idea.id} value={idea.id}>
                  <KanbanItemHandle asChild>
                    <Link href={paths.formHref(idea.id)} draggable={false}>
                      <IdeaCardBody idea={idea} />
                    </Link>
                  </KanbanItemHandle>
                </KanbanItem>
              ))}
              {(columns[key]?.length ?? 0) === 0 && (
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
