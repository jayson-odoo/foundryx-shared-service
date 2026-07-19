'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { ArrowLeft, ChevronUp } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { ideationEmbedService } from '@/services/ideation-embed-service';
import { IDEA_SOURCE_LABEL, IDEA_STATUS_LABEL, type Idea } from '@/types/ideation';
import { useEmbedSession, EmbedExpired, EmbedLoading } from './embed-session';

/**
 * Chrome-less, READ-ONLY idea detail rendered inside the host iframe
 * (PLAN-ideation-embed-sso §9, AC-E-8/11). Every section renders even when empty
 * (CRUD UX standard). Navigation stays in the iframe: the back link carries the
 * fragment token so the session survives.
 */
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-1">
      <h2 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{title}</h2>
      <div className="text-sm text-foreground">{children}</div>
    </section>
  );
}

const empty = <span className="text-muted-foreground">Not provided</span>;

export function EmbedIdeaDetail({ ideaId }: { ideaId: string }) {
  const { status } = useEmbedSession();
  const [idea, setIdea] = useState<Idea | null>(null);
  const [failed, setFailed] = useState(false);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    if (status !== 'ready') return;
    let cancelled = false;
    ideationEmbedService
      .getIdea(ideaId)
      .then((row) => !cancelled && setIdea(row))
      .catch((e: unknown) => {
        if (cancelled) return;
        // 404 = idea not in this tenant / gone → a clean not-found, NOT expired.
        if (e && typeof e === 'object' && 'status' in e && (e as { status: number }).status === 404) {
          setNotFound(true);
        } else {
          setFailed(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [status, ideaId]);

  const tokenHash = typeof window !== 'undefined' ? window.location.hash : '';

  if (status === 'loading') return <EmbedLoading />;
  if (status === 'expired' || failed) return <EmbedExpired />;

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-3xl flex-col gap-6 p-4 sm:p-6">
      <Link
        href={`/embed/ideas${tokenHash}`}
        className="inline-flex w-fit items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden />
        All ideas
      </Link>

      {notFound ? (
        <div className="rounded-lg border border-dashed border-border p-10 text-center">
          <p className="text-sm text-muted-foreground">This idea is no longer available.</p>
        </div>
      ) : idea === null ? (
        <p className="text-sm text-muted-foreground">Loading idea…</p>
      ) : (
        <article className="flex flex-col gap-6">
          <header className="flex items-start gap-4">
            <div className="flex min-w-10 flex-col items-center rounded-md bg-muted px-2 py-1 text-sm">
              <ChevronUp className="size-4 text-muted-foreground" aria-hidden />
              <span className="font-semibold text-foreground">{idea.upvotes}</span>
            </div>
            <div className="flex min-w-0 flex-1 flex-col gap-2">
              <h1 className="text-lg font-semibold leading-snug text-foreground">{idea.problem}</h1>
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="secondary">{idea.productName}</Badge>
                <Badge variant="outline">{IDEA_STATUS_LABEL[idea.status]}</Badge>
                <Badge variant="outline" appearance="light">
                  {IDEA_SOURCE_LABEL[idea.source]}
                </Badge>
              </div>
            </div>
          </header>

          <div className="grid gap-6 sm:grid-cols-2">
            <Section title="Submitter">{idea.submitterName || empty}</Section>
            <Section title="Department">{idea.department || empty}</Section>
            <Section title="Proposed solution">{idea.proposedSolution || empty}</Section>
            <Section title="Impact">{idea.impact || empty}</Section>
          </div>

          <Section title="Raw notes">
            {idea.rawText ? (
              <p className="whitespace-pre-wrap">{idea.rawText}</p>
            ) : (
              empty
            )}
          </Section>

          <Section title="Attachments">
            {idea.attachments && idea.attachments.length > 0 ? (
              <ul className="list-inside list-disc">
                {idea.attachments.map((a) => (
                  <li key={a.id}>{a.name}</li>
                ))}
              </ul>
            ) : (
              <span className="text-muted-foreground">No attachments</span>
            )}
          </Section>
        </article>
      )}
    </div>
  );
}
