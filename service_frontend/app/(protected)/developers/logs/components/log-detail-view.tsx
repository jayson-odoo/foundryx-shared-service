'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Braces, GitBranch, Info, LoaderCircleIcon } from 'lucide-react';
import { useForm } from 'react-hook-form';
import { Container } from '@/components/common/container';
import { Button } from '@/components/ui/button';
import { Form } from '@/components/ui/form';
import { Label } from '@/components/ui/label';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { cn } from '@/lib/utils';
import { ResourceForm, type ResourceFormConfig } from '@/components/platform/resource-form';
import { StatusBadge } from '@/components/platform/status-badge';
import { ClampedText } from '@/components/platform/clamped-text';
import { useDatetime } from '@/hooks/use-datetime';
import { useWorkspaceName } from '@/hooks/use-workspace-name';
import { useIntegrationLogNav } from '@/hooks/use-integration-log-nav';
import { integrationLogService } from '@/services/integration-log-service';
import { workspaceFormPath } from '@/app/(protected)/omnichannel/settings/workspaces/components/paths';
import type { IntegrationLogDetail } from '@/types/integration-logs';
import {
  DEVELOPER_LOGS_PATH,
  LOG_SOURCE_REGISTRY,
  LOG_STATUS_REGISTRY,
  integrationLogDetailPath,
} from './log-badges';
import { TraceTimeline } from './trace-timeline';

/** A trace id styled as an inline link that jumps to the Trace tab. */
function TraceLink({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(PRESSED_CLASS, 'text-primary hover:underline font-mono text-xs')}
    >
      {label}
    </button>
  );
}

function OverviewRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-1 md:grid-cols-[200px_1fr] md:items-center md:gap-4">
      <Label className="text-muted-foreground text-sm">{label}</Label>
      <div className="min-w-0 text-sm">{children}</div>
    </div>
  );
}

function JsonBlock({ value }: { value: Record<string, unknown> | null }) {
  if (value == null) {
    return <p className="text-muted-foreground text-sm">No payload captured.</p>;
  }
  return (
    <pre className="max-h-[520px] overflow-auto rounded-md bg-muted px-3 py-2 font-mono text-xs">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

export function LogDetailView({ logId }: { logId: string }) {
  const [log, setLog] = useState<IntegrationLogDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const { formatDateTime } = useDatetime();
  const router = useRouter();
  const form = useForm({ mode: 'onTouched' });

  // Clickable trace id → in-page switch to the Trace tab. `initialTabId` only
  // applies on mount, so a nonce-keyed remount re-forces it on every click.
  const [forcedTab, setForcedTab] = useState('overview');
  const [tabNonce, setTabNonce] = useState(0);
  const goToTrace = useCallback(() => {
    setForcedTab('trace');
    setTabNonce((n) => n + 1);
  }, []);

  // Resolve the workspace NAME (frontend-side, no core→module coupling).
  const { name: workspaceName } = useWorkspaceName(log?.workspaceId);
  // Circular prev/next across the log list.
  const nav = useIntegrationLogNav(logId);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    integrationLogService.get(logId).then((row) => {
      if (cancelled) return;
      setLog(row);
      setIsLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [logId]);

  const config = useMemo<ResourceFormConfig<IntegrationLogDetail> | null>(() => {
    if (!log) return null;
    return {
      breadcrumb: [
        { label: 'Developers' },
        { label: 'Logs', href: DEVELOPER_LOGS_PATH },
        { label: log.operation },
      ],
      backHref: DEVELOPER_LOGS_PATH,
      title: log.operation,
      subtitle: log.traceId ? (
        <span className="text-muted-foreground text-sm">
          Trace <TraceLink label={log.traceId} onClick={goToTrace} />
        </span>
      ) : undefined,
      tabs: [
        {
          id: 'overview',
          label: 'Overview',
          icon: Info,
          render: () => (
            <div className="flex flex-col gap-4 py-2">
              <OverviewRow label="Source">
                <StatusBadge status={log.source} registry={LOG_SOURCE_REGISTRY} size="sm" />
              </OverviewRow>
              <OverviewRow label="Operation">
                <code className="text-xs">{log.operation}</code>
              </OverviewRow>
              <OverviewRow label="Status">
                <div className="flex items-center gap-2">
                  <StatusBadge status={log.status} registry={LOG_STATUS_REGISTRY} size="sm" />
                  {log.statusCode != null && (
                    <span className="text-muted-foreground text-xs">{log.statusCode}</span>
                  )}
                </div>
              </OverviewRow>
              <OverviewRow label="Latency">
                {log.latencyMs != null ? `${log.latencyMs} ms` : '-'}
              </OverviewRow>
              <OverviewRow label="Workspace">
                {log.workspaceId ? (
                  <Link
                    href={workspaceFormPath(log.workspaceId)}
                    className="text-primary hover:underline text-xs"
                  >
                    {workspaceName ?? log.workspaceId}
                  </Link>
                ) : (
                  '-'
                )}
              </OverviewRow>
              <OverviewRow label="API key">
                {log.apiKeyId ? <code className="text-xs">{log.apiKeyId}</code> : '-'}
              </OverviewRow>
              <OverviewRow label="Trace id">
                {log.traceId ? <TraceLink label={log.traceId} onClick={goToTrace} /> : '-'}
              </OverviewRow>
              <OverviewRow label="External ref">
                {log.externalRef ? <code className="text-xs">{log.externalRef}</code> : '-'}
              </OverviewRow>
              <OverviewRow label="Time">{formatDateTime(log.createdAt)}</OverviewRow>
              {log.status === 'error' && log.errorCode && (
                <OverviewRow label="Error code">
                  <code data-testid="log-error-code" className="text-destructive text-xs">
                    {log.errorCode}
                  </code>
                </OverviewRow>
              )}
              {log.errorMessage && (
                <OverviewRow label="Error">
                  <pre
                    data-testid="log-error"
                    className="text-destructive bg-destructive/5 whitespace-pre-wrap rounded-md px-3 py-2 font-mono text-xs"
                  >
                    <ClampedText text={log.errorMessage} lines={4} />
                  </pre>
                </OverviewRow>
              )}
            </div>
          ),
        },
        {
          id: 'trace',
          label: 'Trace',
          icon: GitBranch,
          render: () => (
            <div className="flex flex-col gap-4 py-2">
              <TraceTimeline traceId={log.traceId} currentId={log.id} />
            </div>
          ),
        },
        {
          id: 'payloads',
          label: 'Payloads',
          icon: Braces,
          render: () => (
            <div className="flex flex-col gap-4 py-2">
              <div className="flex flex-col gap-2">
                <Label className="text-muted-foreground text-sm">Request (redacted)</Label>
                <JsonBlock value={log.requestSummary} />
              </div>
              <div className="flex flex-col gap-2">
                <Label className="text-muted-foreground text-sm">Response (redacted)</Label>
                <JsonBlock value={log.responseSummary} />
              </div>
            </div>
          ),
        },
      ],
      initialTabId: forcedTab,
      // Circular record-nav (‹ N / M ›) top-right near Back - reuses the shell's
      // built-in inlineNav pager rather than a hand-rolled one.
      inlineNav:
        nav.total > 1 && nav.index >= 0
          ? {
              index: nav.index,
              total: nav.total,
              onPrev: () => nav.prevId && router.push(integrationLogDetailPath(nav.prevId)),
              onNext: () => nav.nextId && router.push(integrationLogDetailPath(nav.nextId)),
            }
          : undefined,
      actions: [],
      actionRows: [log],
      // Read-only surface - log rows are historical facts (no Edit toggle).
      editable: false,
      isDirty: false,
      onSave: () => true,
      onCancel: () => undefined,
    };
  }, [log, formatDateTime, forcedTab, goToTrace, workspaceName, nav, router]);

  if (isLoading) {
    return (
      <Container width="fluid">
        <div className="text-muted-foreground flex items-center justify-center py-24">
          <LoaderCircleIcon className="size-6 animate-spin" />
        </div>
      </Container>
    );
  }

  if (!log || !config) {
    return (
      <Container width="fluid">
        <div className="flex flex-col items-center gap-3 py-24 text-center">
          <p className="text-sm font-medium">Log not found.</p>
          <Button variant="outline" size="sm" asChild>
            <Link href={DEVELOPER_LOGS_PATH}>Back to logs</Link>
          </Button>
        </div>
      </Container>
    );
  }

  return (
    <Container width="fluid">
      <Form {...form}>
        {/* Nonce-keyed so a trace-id click re-forces the Trace tab every time. */}
        <ResourceForm key={`${log.id}:${tabNonce}`} config={config} />
      </Form>
    </Container>
  );
}
