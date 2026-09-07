'use client';

/**
 * Migration job detail (AC-MIG-08) - job facts, progress bar, the counts
 * report and the per-entity failure table, polling while in flight (the
 * `jobs/[id]/page.tsx` reference). Read-only: this is a completed/in-flight
 * job record, never a re-edit of the mapping that created it.
 */
import { use, useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { LoaderCircle } from 'lucide-react';
import { RequirePermission } from '@/components/common/require-permission';
import { PageHeader } from '@/components/platform/page-header';
import { Container } from '@/components/common/container';
import { Card, CardContent, CardHeader, CardHeading, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { Skeleton } from '@/components/ui/skeleton';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import { StatusBadge } from '@/components/platform/status-badge';
import { useDatetime } from '@/hooks/use-datetime';
import { respondioMigrationService } from '@/services/respondio-migration-service';
import { MIGRATION_JOB_IN_FLIGHT, type MigrationJob } from '@/types/respondio-migration';
import { useMigrationActions } from '../components/use-migration-actions';
import { MIGRATION_MODE_LABEL, MIGRATION_STATUS_REGISTRY } from '../components/migration-status';
import { MigrationReportCard } from '../components/migration-report-card';
import { MigrationFailuresTable } from '../components/migration-failures-table';
import { migrationListPath } from '../components/paths';

const POLL_MS = 3000;

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 py-1">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}

export default function MigrationJobDetailPage({ params }: { params: Promise<{ jobId: string }> }) {
  const { jobId } = use(params);
  const { formatDateTime } = useDatetime();
  const actions = useMigrationActions();
  const [job, setJob] = useState<MigrationJob | null>(null);
  const [notFound, setNotFound] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = useCallback(async () => {
    try {
      setJob(await respondioMigrationService.getJob(jobId));
    } catch {
      setNotFound(true);
    }
  }, [jobId]);

  useEffect(() => {
    let active = true;
    const tick = async () => {
      if (!active) return;
      await refresh();
      if (!active) return;
      setJob((cur) => {
        if (cur && MIGRATION_JOB_IN_FLIGHT.has(cur.status)) {
          timer.current = setTimeout(tick, POLL_MS);
        }
        return cur;
      });
    };
    void tick();
    return () => {
      active = false;
      if (timer.current) clearTimeout(timer.current);
    };
  }, [refresh]);

  if (notFound) {
    return (
      <Container width="fluid">
        <div className="flex flex-col items-center gap-3 py-24 text-center">
          <p className="text-sm font-medium">Migration job not found.</p>
          <Button variant="outline" size="sm" asChild>
            <Link href={migrationListPath}>Back to migration</Link>
          </Button>
        </div>
      </Container>
    );
  }

  if (!job) {
    return (
      <Container width="fluid">
        <Skeleton className="h-64 w-full" />
      </Container>
    );
  }

  // Review round 1, finding S6 - `progressTotal` stays 0 for the entire run
  // (the backend only knows the true total once every phase has finished,
  // `finish_done`'s own `set_total` call) - a 0%-forever bar is worse than
  // no bar at all, so this renders a plain running count while the total is
  // unknown rather than a misleading stalled percentage.
  const hasTotal = job.progressTotal > 0;
  const pct = hasTotal ? Math.round((job.progressDone / job.progressTotal) * 100) : 0;

  return (
    <RequirePermission permission="omnichannel_migration.read">
      <Container width="fluid">
        <PageHeader
          title={job.spaceLabel}
          description={
            <div className="flex items-center gap-2">
              <StatusBadge status={job.status} registry={MIGRATION_STATUS_REGISTRY} />
              {MIGRATION_JOB_IN_FLIGHT.has(job.status) && (
                <LoaderCircle className="text-muted-foreground size-4 animate-spin" />
              )}
            </div>
          }
          actions={
            <ActionMenu actions={actions} rows={[job]} runtime={{ reload: () => void refresh() }} surface="form" />
          }
        />

        <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardHeading>
                <CardTitle>Progress</CardTitle>
              </CardHeading>
            </CardHeader>
            <CardContent className="space-y-4">
              {hasTotal && <Progress value={pct} />}
              <div className="flex flex-wrap gap-2 text-sm text-muted-foreground">
                <span>{hasTotal ? `${job.progressDone}/${job.progressTotal} processed` : `${job.progressDone} processed`}</span>
                {job.progressFailed > 0 && <span className="text-destructive">{job.progressFailed} failed</span>}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardHeading>
                <CardTitle>Details</CardTitle>
              </CardHeading>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <Row label="Mode" value={MIGRATION_MODE_LABEL[job.mode]} />
              <Row label="Target workspace" value={job.workspaceName} />
              <Row label="Started" value={job.startedAt ? formatDateTime(job.startedAt) : '-'} />
              <Row label="Finished" value={job.finishedAt ? formatDateTime(job.finishedAt) : '-'} />
              <Row label="Started by" value={job.actorUserName ?? '-'} />
            </CardContent>
          </Card>
        </div>

        {job.report && (
          <div className="mt-5">
            <MigrationReportCard report={job.report} />
          </div>
        )}

        {job.failureCount > 0 && (
          <MigrationFailuresTable jobId={job.id} rows={job.failureSample} totalFailures={job.failureCount} />
        )}

        <Card className="mt-5">
          <CardHeader>
            <CardHeading>
              <CardTitle>Logs</CardTitle>
            </CardHeading>
          </CardHeader>
          <CardContent>
            {job.logs.length === 0 ? (
              <p className="text-muted-foreground text-sm">No log entries yet.</p>
            ) : (
              <ul className="space-y-1.5 font-mono text-xs">
                {job.logs.map((entry, i) => (
                  <li key={i} className="flex flex-wrap gap-x-2 gap-y-0.5">
                    <span className="text-muted-foreground shrink-0">{formatDateTime(entry.ts)}</span>
                    <span
                      className={
                        entry.level === 'error'
                          ? 'text-destructive shrink-0 uppercase'
                          : entry.level === 'warning'
                            ? 'shrink-0 uppercase text-amber-600'
                            : 'text-muted-foreground shrink-0 uppercase'
                      }
                    >
                      {entry.level}
                    </span>
                    <span className="min-w-0 break-words">{entry.message}</span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </Container>
    </RequirePermission>
  );
}
