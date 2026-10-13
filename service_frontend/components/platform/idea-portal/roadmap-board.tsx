'use client';

import type { PortalColumn } from '@/types/idea-portal';
import { colorToHex } from '@/components/platform/status-badge';
import { IdeaCard } from './idea-card';

export interface RoadmapBoardProps {
  columns: PortalColumn[];
  ideaHref: (id: string) => string;
  onVote: (id: string) => void;
}

/** Read-only roadmap: one column per roadmap stage, cards by upvotes. Stacks
 * to one column on mobile. */
export function RoadmapBoard({ columns, ideaHref, onVote }: RoadmapBoardProps) {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4" data-testid="portal-roadmap">
      {columns.map((col) => (
        <section
          key={col.key}
          aria-label={col.title}
          data-column={col.key}
          className="flex min-w-0 flex-col rounded-xl border border-border bg-muted/40 p-3"
        >
          <header className="mb-3 flex items-center gap-2 text-sm font-semibold text-foreground">
            <span className="size-2 rounded-full" style={{ backgroundColor: colorToHex(col.color) }} aria-hidden />
            {col.title}
            <span className="ml-auto text-xs font-normal text-muted-foreground">{col.count}</span>
          </header>
          <div className="flex flex-col gap-2">
            {col.ideas.length === 0 ? (
              <p className="py-4 text-center text-xs text-muted-foreground">No ideas</p>
            ) : (
              col.ideas.map((idea) => (
                <IdeaCard key={idea.id} idea={idea} href={ideaHref(idea.id)} onVote={onVote} />
              ))
            )}
          </div>
        </section>
      ))}
    </div>
  );
}
