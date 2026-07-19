'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { ChevronUp } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { ClampedText } from '@/components/platform/clamped-text';
import { ideationEmbedService } from '@/services/ideation-embed-service';
import { IDEA_SOURCE_LABEL, IDEA_STATUS_LABEL, type Idea } from '@/types/ideation';
import { useEmbedSession, EmbedExpired, EmbedLoading } from './embed-session';

/**
 * Chrome-less, READ-ONLY Ideas board rendered inside the host iframe
 * (PLAN-ideation-embed-sso §9, AC-E-8). Reuses the ideation `Idea` type + the
 * shared label maps + UI primitives (Badge, ClampedText) so it matches the
 * operator board's visual language — data fetching/serialization stay in the
 * backend + service (no logic forked). Rows link WITHIN the iframe to
 * `/embed/ideas/{id}#token=…` so navigation keeps the session (AC-E-11).
 */
export function EmbedIdeasBoard() {
  const { status } = useEmbedSession();
  const [ideas, setIdeas] = useState<Idea[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [search, setSearch] = useState('');

  useEffect(() => {
    if (status !== 'ready') return;
    let cancelled = false;
    ideationEmbedService
      .listIdeas()
      .then((rows) => !cancelled && setIdeas(rows))
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, [status]);

  // Preserve the fragment token when navigating to a detail (keeps the session).
  const tokenHash = typeof window !== 'undefined' ? window.location.hash : '';

  const filtered = useMemo(() => {
    if (!ideas) return [];
    const s = search.trim().toLowerCase();
    if (!s) return ideas;
    return ideas.filter(
      (r) =>
        r.problem.toLowerCase().includes(s) ||
        r.submitterName.toLowerCase().includes(s) ||
        r.productName.toLowerCase().includes(s),
    );
  }, [ideas, search]);

  if (status === 'loading') return <EmbedLoading />;
  if (status === 'expired' || failed) return <EmbedExpired />;

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-5xl flex-col gap-4 p-4 sm:p-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-lg font-semibold text-foreground">Ideas</h1>
        <p className="text-sm text-muted-foreground">
          Ideas captured for your workspace. Select one to see the details.
        </p>
      </div>

      <input
        type="search"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search ideas…"
        aria-label="Search ideas"
        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring sm:max-w-xs"
      />

      {ideas === null ? (
        <p className="text-sm text-muted-foreground">Loading ideas…</p>
      ) : filtered.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-10 text-center">
          <p className="text-sm text-muted-foreground">
            {ideas.length === 0 ? 'No ideas captured yet.' : 'No ideas match your search.'}
          </p>
        </div>
      ) : (
        <ul className="flex flex-col divide-y divide-border overflow-hidden rounded-lg border border-border">
          {filtered.map((idea) => (
            <li key={idea.id}>
              <Link
                href={`/embed/ideas/${encodeURIComponent(idea.id)}${tokenHash}`}
                className="flex items-start gap-4 p-4 transition-colors hover:bg-muted/50"
              >
                <div className="flex min-w-10 flex-col items-center pt-0.5 text-sm text-muted-foreground">
                  <ChevronUp className="size-4" aria-hidden />
                  <span className="font-medium text-foreground">{idea.upvotes}</span>
                </div>
                <div className="flex min-w-0 flex-1 flex-col gap-2">
                  <ClampedText text={idea.problem} lines={2} />
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="secondary">{idea.productName}</Badge>
                    <Badge variant="outline">{IDEA_STATUS_LABEL[idea.status]}</Badge>
                    <Badge variant="outline" appearance="light">
                      {IDEA_SOURCE_LABEL[idea.source]}
                    </Badge>
                    <span className="text-xs text-muted-foreground">{idea.submitterName}</span>
                  </div>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
