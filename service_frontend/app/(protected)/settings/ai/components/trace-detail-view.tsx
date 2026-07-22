'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { ChevronLeft, LoaderCircleIcon } from 'lucide-react';
import { Container } from '@/components/common/container';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { useDatetime } from '@/hooks/use-datetime';
import { aiService } from '@/services/ai-service';
import type { AiSpan, AiTraceDetail } from '@/types/ai';
import { AI_TRACES_PATH } from './paths';

/** Truncation the backend already marked — surfaced so a clipped payload is
 *  never mistaken for a short one. */
function wasTruncated(payload: unknown): boolean {
  return (
    typeof payload === 'object' &&
    payload !== null &&
    (payload as Record<string, unknown>)._truncated === true
  );
}

function PayloadBlock({ label, payload }: { label: string; payload: unknown }) {
  if (payload === null || payload === undefined) return null;
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <div className="flex items-center gap-2">
        <span className="text-xs font-medium text-foreground">{label}</span>
        {wasTruncated(payload) && (
          <Badge variant="secondary" appearance="light" size="sm">
            Truncated
          </Badge>
        )}
      </div>
      <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted p-3 font-mono text-xs text-muted-foreground">
        {JSON.stringify(payload, null, 2)}
      </pre>
    </div>
  );
}

function SpanRow({ span, index }: { span: AiSpan; index: number }) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-3 py-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-medium text-muted-foreground">
            {index + 1}
          </span>
          <span className="font-mono text-xs text-foreground">{span.spanKind}</span>
          {span.name && span.name !== span.spanKind && (
            <span className="text-xs text-muted-foreground">{span.name}</span>
          )}
          <Badge
            variant={span.status === 'ok' ? 'success' : 'destructive'}
            appearance="light"
            size="sm"
          >
            {span.status === 'ok' ? 'OK' : 'Error'}
          </Badge>
          <span className="text-xs text-muted-foreground">{span.latencyMs} ms</span>
          {(span.tokensIn > 0 || span.tokensOut > 0) && (
            <span className="text-xs text-muted-foreground">
              {span.tokensIn} in / {span.tokensOut} out
            </span>
          )}
        </div>
        {span.error && <p className="text-xs text-destructive">{span.error}</p>}
        <div className="grid gap-3 lg:grid-cols-2">
          <PayloadBlock label="Input" payload={span.inputJson} />
          <PayloadBlock label="Output" payload={span.outputJson} />
        </div>
      </CardContent>
    </Card>
  );
}

export interface TraceDetailViewProps {
  traceId: string;
}

/**
 * A trace's steps as a FLAT ordered list (Bi-D17).
 *
 * Deliberately not a tree: slice 1 only ever produces depth-1 sequences, and a
 * tree renderer for a flat list is cost with no payoff. `parentId` and
 * `dottedOrder` are already carried on every span, so the tree is a renderer
 * change when real depth (agent tool loops) arrives — not a migration.
 */
export function TraceDetailView({ traceId }: TraceDetailViewProps) {
  const [trace, setTrace] = useState<AiTraceDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const { formatDateTime } = useDatetime();

  useEffect(() => {
    let cancelled = false;
    aiService
      .getTrace(traceId)
      .then((result) => {
        if (!cancelled) setTrace(result);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [traceId]);

  if (isLoading) {
    return (
      <Container width="fluid">
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <LoaderCircleIcon className="size-6 animate-spin" />
        </div>
      </Container>
    );
  }

  if (!trace) {
    return (
      <Container width="fluid">
        <div className="flex flex-col items-center gap-3 py-24 text-center">
          <p className="text-sm font-medium">Trace not found.</p>
          <Button variant="outline" size="sm" asChild>
            <Link href={AI_TRACES_PATH}>Back to traces</Link>
          </Button>
        </div>
      </Container>
    );
  }

  return (
    <Container width="fluid">
      <div className="flex flex-col gap-5 py-5">
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="ghost" size="sm" asChild>
            <Link href={AI_TRACES_PATH}>
              <ChevronLeft className="size-4" />
              Traces
            </Link>
          </Button>
        </div>

        <Card>
          <CardContent className="grid gap-4 py-5 sm:grid-cols-2 lg:grid-cols-4">
            <div className="flex flex-col gap-0.5">
              <span className="text-xs text-muted-foreground">Agent</span>
              <span className="text-sm font-medium text-foreground">
                {trace.agentName || '—'}
              </span>
            </div>
            <div className="flex flex-col gap-0.5">
              <span className="text-xs text-muted-foreground">Model</span>
              <span className="text-sm text-foreground">{trace.model || '—'}</span>
              <span className="text-xs text-muted-foreground">{trace.provider}</span>
            </div>
            <div className="flex flex-col gap-0.5">
              <span className="text-xs text-muted-foreground">Tokens</span>
              <span className="text-sm text-foreground">
                {trace.tokensIn} in / {trace.tokensOut} out
              </span>
            </div>
            <div className="flex flex-col gap-0.5">
              <span className="text-xs text-muted-foreground">Latency</span>
              <span className="text-sm text-foreground">{trace.latencyMs} ms</span>
            </div>
            <div className="flex flex-col gap-0.5">
              <span className="text-xs text-muted-foreground">Status</span>
              <div className="flex flex-wrap items-center gap-1.5">
                <Badge
                  variant={trace.status === 'ok' ? 'success' : 'destructive'}
                  appearance="light"
                  size="sm"
                >
                  {trace.status === 'ok' ? 'OK' : 'Error'}
                </Badge>
                {trace.flagged && (
                  <Badge variant="warning" appearance="light" size="sm">
                    Flagged
                  </Badge>
                )}
              </div>
            </div>
            <div className="flex flex-col gap-0.5">
              <span className="text-xs text-muted-foreground">Prompt</span>
              <span className="font-mono text-xs text-foreground">
                {trace.skillKey ?? '—'}
                {trace.promptVersion ? ` v${trace.promptVersion}` : ''}
              </span>
            </div>
            <div className="flex flex-col gap-0.5">
              <span className="text-xs text-muted-foreground">When</span>
              <span className="text-sm text-foreground">
                {trace.createdAt ? formatDateTime(trace.createdAt) : '—'}
              </span>
            </div>
            <div className="flex flex-col gap-0.5">
              <span className="text-xs text-muted-foreground">Steps</span>
              <span className="text-sm text-foreground">{trace.spanCount}</span>
            </div>
          </CardContent>
        </Card>

        {trace.error && (
          <Card>
            <CardContent className="py-4">
              <p className="text-sm text-destructive">{trace.error}</p>
            </CardContent>
          </Card>
        )}

        <div className="flex flex-col gap-3">
          {trace.spans.map((span, index) => (
            <SpanRow key={span.id} span={span} index={index} />
          ))}
          {trace.spans.length === 0 && (
            <p className="py-12 text-center text-sm text-muted-foreground">
              No steps recorded.
            </p>
          )}
        </div>
      </div>
    </Container>
  );
}
