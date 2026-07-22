'use client';

import Link from 'next/link';
import { LoaderCircleIcon } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { useBrIdeas } from '@/hooks/use-br-ideas';

export interface BrIdeasTabProps {
  brId: string;
  reloadToken: number;
}

/** Ideas tab — the linked ideas feeding this BR (lineage, AC-BI-35). Read-only
 * list in S2; linking mid-grill lands in S3/S4. Data via `useBrIdeas`
 * (UI → hook → service). */
export function BrIdeasTab({ brId, reloadToken }: BrIdeasTabProps) {
  const { ideas } = useBrIdeas(brId, reloadToken);

  if (ideas === null) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        <LoaderCircleIcon className="size-5 animate-spin" />
      </div>
    );
  }

  if (ideas.length === 0) {
    return (
      <p className="py-12 text-center text-sm text-muted-foreground">
        No linked ideas.
      </p>
    );
  }

  return (
    <Card>
      <CardContent className="py-2 divide-y divide-border">
        {ideas.map((idea) => (
          <Link
            key={idea.id}
            href={`/ideation/ideas/${idea.id}`}
            className="flex items-center justify-between gap-3 py-3 hover:bg-muted/40 -mx-2 px-2 rounded-md"
          >
            <span className="text-sm text-foreground line-clamp-2">{idea.problem}</span>
            <div className="flex shrink-0 items-center gap-2">
              <span className="text-xs text-muted-foreground">{idea.submitterName}</span>
              <Badge variant="secondary">{idea.productName}</Badge>
            </div>
          </Link>
        ))}
      </CardContent>
    </Card>
  );
}
