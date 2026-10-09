'use client';

import { useEffect, useRef } from 'react';
import { ExternalLink } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { ClampedText } from '@/components/platform/clamped-text';
import { useDatetime } from '@/hooks/use-datetime';
import type { BuildEvent, BuildInfo } from '@/types/business-requirement';
import { BrPlaceholderTab } from './br-placeholder-tab';

export interface BrTraceTabProps {
  brId: string;
  /** The BR's build state; null until the first load. */
  build: BuildInfo | null;
  /** Refetch the build (called when the tab opens and when the window regains focus). */
  reload: () => void;
}

/** A closing entry (the crew moved the BR to Delivered) reads as success. */
function isSuccess(event: BuildEvent): boolean {
  return event.status === 'merged' || event.status === 'released';
}

function latest<K extends 'prUrl' | 'handtestUrl'>(
  events: BuildEvent[],
  key: K,
  fallback: string | null,
): string | null {
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const value = events[i][key];
    if (value) return value;
  }
  return fallback;
}

function ExternalAnchor({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1 text-primary hover:underline"
    >
      {children}
      <ExternalLink className="size-3.5 shrink-0" aria-hidden />
    </a>
  );
}

function SummaryCell({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="min-w-0 text-sm font-medium">{children}</span>
    </div>
  );
}

/**
 * Trace tab (AC-STB-19): a build summary card (issue, latest stage, latest PR and
 * hand-test links) over the crew's timeline, oldest first. Refetches on open and
 * on window focus; there is no polling.
 */
export function BrTraceTab({ brId, build, reload }: BrTraceTabProps) {
  const { formatDateTime } = useDatetime();
  const reloadRef = useRef(reload);
  reloadRef.current = reload;

  useEffect(() => {
    reloadRef.current();
    const onFocus = () => reloadRef.current();
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, [brId]);

  if (!build || build.state === 'none') {
    return <BrPlaceholderTab label="Not sent to build yet." />;
  }

  const events = [...build.events].sort((a, b) => a.seq - b.seq);
  const lastEvent = events[events.length - 1];
  const stage = lastEvent?.stage ?? build.stage;
  const prUrl = latest(events, 'prUrl', build.prUrl);
  const handtestUrl = latest(events, 'handtestUrl', build.handtestUrl);
  const repoShort = build.repo?.split('/').pop() ?? 'issue';
  const prNumber = prUrl?.match(/\/pull\/(\d+)/)?.[1];

  return (
    <div className="flex flex-col gap-4">
      <div
        data-slot="build-summary"
        className="grid grid-cols-2 gap-4 rounded-lg border bg-card p-4 sm:grid-cols-4"
      >
        <SummaryCell label="Issue">
          {build.issueUrl ? (
            <ExternalAnchor href={build.issueUrl}>
              {`${repoShort} #${build.issueNumber ?? ''}`.trim()}
            </ExternalAnchor>
          ) : (
            '-'
          )}
        </SummaryCell>
        <SummaryCell label="Stage">
          {stage ? (
            <Badge variant={lastEvent && isSuccess(lastEvent) ? 'success' : 'info'} appearance="light" size="sm">
              {stage}
            </Badge>
          ) : (
            '-'
          )}
        </SummaryCell>
        <SummaryCell label="Pull request">
          {prUrl ? <ExternalAnchor href={prUrl}>{prNumber ? `PR #${prNumber}` : 'Open PR'}</ExternalAnchor> : '-'}
        </SummaryCell>
        <SummaryCell label="Hand test">
          {handtestUrl ? <ExternalAnchor href={handtestUrl}>Open test copy</ExternalAnchor> : '-'}
        </SummaryCell>
      </div>

      <ol className="flex flex-col rounded-lg border bg-card p-4">
        {events.map((event) => {
          const success = isSuccess(event);
          return (
            <li
              key={event.id}
              data-tone={success ? 'success' : undefined}
              className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 py-2 sm:grid-cols-[9rem_auto_1fr]"
            >
              <span className="col-span-2 text-xs text-muted-foreground sm:col-span-1">
                {formatDateTime(event.createdAt)}
              </span>
              <span
                aria-hidden
                className={`mt-1.5 size-2 rounded-full ${success ? 'bg-success' : 'bg-primary'}`}
              />
              <div className="flex min-w-0 flex-col gap-1">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={success ? 'success' : 'info'} appearance="light" size="sm">
                    {event.stage}
                  </Badge>
                  {event.actorName && (
                    <span className="text-xs text-muted-foreground">{event.actorName}</span>
                  )}
                  {event.prUrl && <ExternalAnchor href={event.prUrl}>PR</ExternalAnchor>}
                  {event.handtestUrl && (
                    <ExternalAnchor href={event.handtestUrl}>Hand test</ExternalAnchor>
                  )}
                </div>
                <ClampedText text={event.message} lines={3} className="text-sm" />
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
