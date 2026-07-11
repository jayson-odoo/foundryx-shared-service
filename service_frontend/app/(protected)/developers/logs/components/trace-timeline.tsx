'use client';

/**
 * Trace timeline (sprint-4/12 Slice 2, AC-DLC-18) — the ordered legs of one
 * consumption (inbound API → outbound Meta → webhook delivery), each with its
 * source badge, status, latency + time. Clicking a leg opens that leg's detail;
 * the currently-viewed leg is highlighted. Reuses the shell primitives
 * (StatusBadge + the shared source/status registries, `useDatetime`).
 */
import Link from 'next/link';
import { LoaderCircleIcon } from 'lucide-react';
import { StatusBadge } from '@/components/platform/status-badge';
import { ClampedText } from '@/components/platform/clamped-text';
import { useDatetime } from '@/hooks/use-datetime';
import { useIntegrationLogTrace } from '@/hooks/use-integration-log-trace';
import type { IntegrationLogItem } from '@/types/integration-logs';
import {
  integrationLogDetailPath,
  LOG_SOURCE_REGISTRY,
  LOG_STATUS_REGISTRY,
} from './log-badges';

export function TraceTimeline({
  traceId,
  currentId,
}: {
  traceId: string | null;
  currentId: string;
}) {
  const { legs, isLoading } = useIntegrationLogTrace(traceId);
  const { formatDateTime } = useDatetime();

  if (!traceId) {
    return (
      <p className="text-muted-foreground text-sm">
        This activity is not part of a correlated trace.
      </p>
    );
  }

  if (isLoading) {
    return (
      <div className="text-muted-foreground flex items-center justify-center py-10">
        <LoaderCircleIcon className="size-5 animate-spin" />
      </div>
    );
  }

  if (legs.length === 0) {
    return <p className="text-muted-foreground text-sm">No correlated legs found.</p>;
  }

  return (
    <ol className="flex flex-col gap-2" data-testid="trace-timeline">
      {legs.map((leg: IntegrationLogItem, i: number) => {
        const isCurrent = leg.id === currentId;
        return (
          <li key={leg.id} className="flex gap-3">
            {/* Rail: node dot + connecting line. */}
            <div className="flex flex-col items-center pt-3">
              <span
                className={`size-2.5 shrink-0 rounded-full ${
                  leg.status === 'error' ? 'bg-destructive' : 'bg-primary'
                }`}
              />
              {i < legs.length - 1 && <span className="bg-border mt-1 w-px flex-1" />}
            </div>
            <Link
              href={integrationLogDetailPath(leg.id)}
              aria-current={isCurrent ? 'true' : undefined}
              className={`flex min-w-0 flex-1 flex-col gap-2 rounded-lg border p-3 transition-colors sm:flex-row sm:items-center sm:justify-between ${
                isCurrent
                  ? 'border-primary bg-primary/5'
                  : 'hover:bg-accent border-border'
              }`}
            >
              <div className="flex min-w-0 flex-col gap-1">
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  <StatusBadge status={leg.source} registry={LOG_SOURCE_REGISTRY} size="sm" />
                  <ClampedText
                    text={leg.operation}
                    lines={1}
                    className="min-w-0 font-mono text-xs"
                  />
                </div>
                <span className="text-muted-foreground text-xs">
                  {formatDateTime(leg.createdAt)}
                </span>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {leg.latencyMs != null && (
                  <span className="text-muted-foreground text-xs">{leg.latencyMs} ms</span>
                )}
                <StatusBadge status={leg.status} registry={LOG_STATUS_REGISTRY} size="sm" />
              </div>
            </Link>
          </li>
        );
      })}
    </ol>
  );
}
