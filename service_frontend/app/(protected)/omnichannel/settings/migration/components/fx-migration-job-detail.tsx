'use client';

/**
 * A migration job's page with the Foundryx UIUX switch on (slice W2-WS, gap
 * audit "Work that runs in the background"). Same reads, the same polling
 * every 3 s while the job runs, and the same Abort as with the switch off;
 * what changes is how it reads:
 * - Progress says what is happening in words ("Running in the background",
 *   "820 of 1,240 processed, 2 failed"), with the bar only once the server
 *   knows the total.
 * - Abort is an Other Action icon in the page header while the job runs
 *   (one click with no confirm, as today: which actions ask stays as it is).
 * - Times use the 12-hour form.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import {
  MIGRATION_JOB_IN_FLIGHT,
  type MigrationJob,
} from '@/types/respondio-migration';
import { useCan } from '@/hooks/use-can';
import { useDatetime } from '@/hooks/use-datetime';
import { respondioMigrationService } from '@/services/respondio-migration-service';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardHeader,
  CardHeading,
  CardTitle,
} from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Skeleton } from '@/components/ui/skeleton';
import { Container } from '@/components/common/container';
import {
  useRegisterOtherActions,
  type FxOtherActionSpec,
} from '@/components/fx/actions/page-actions-context';
import { PageHeader } from '@/components/platform/page-header';
import { runResourceAction } from '@/components/platform/resource-actions/run-action';
import { StatusBadge } from '@/components/platform/status-badge';
import { MigrationFailuresTable } from './migration-failures-table';
import { fxMigrationHeadline, fxMigrationLine } from './migration-fx';
import { migrationProgressPct } from './migration-progress';
import { MigrationReportCard } from './migration-report-card';
import {
  MIGRATION_MODE_LABEL,
  MIGRATION_STATUS_REGISTRY,
} from './migration-status';
import { MigrationSyncCard } from './migration-sync-card';
import { migrationListPath } from './paths';
import { canOfferSync } from './sync-status';
import {
  MIGRATION_FX_ICONS,
  useMigrationActions,
} from './use-migration-actions';

const POLL_MS = 3000;
const NO_OTHERS: FxOtherActionSpec[] = [];

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 py-1">
      <span className="text-(--fx-ink-3)">{label}</span>
      <span className="min-w-0 break-words text-end font-medium">{value}</span>
    </div>
  );
}

export function FxMigrationJobDetail({ jobId }: { jobId: string }) {
  const { formatDateTime } = useDatetime();
  const { can } = useCan();
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

  const others = useMemo<FxOtherActionSpec[]>(() => {
    if (!job) return NO_OTHERS;
    return actions
      .filter(
        (a) =>
          a.surfaces.form &&
          (!a.permission || can(a.permission)) &&
          (a.isVisible ? a.isVisible([job]) : true),
      )
      .map((a) => ({
        id: a.id,
        label:
          a.id === 'abort'
            ? 'Abort migration'
            : typeof a.label === 'function'
              ? a.label([job])
              : a.label,
        icon: MIGRATION_FX_ICONS[a.id] ?? 'more',
        onClick: () =>
          void runResourceAction(a, [job], { reload: () => void refresh() }),
      }));
  }, [actions, job, can, refresh]);
  useRegisterOtherActions(others);

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

  const running = MIGRATION_JOB_IN_FLIGHT.has(job.status);
  const pct = migrationProgressPct(job.progressDone, job.progressTotal);

  return (
    <Container width="fluid">
      <PageHeader
        title={job.spaceLabel || 'Migration'}
        description={
          <StatusBadge
            status={job.status}
            registry={MIGRATION_STATUS_REGISTRY}
          />
        }
      />

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardHeading>
              <CardTitle>Progress</CardTitle>
            </CardHeading>
          </CardHeader>
          <CardContent className="space-y-3">
            <p
              className="text-sm font-semibold text-(--fx-ink)"
              data-fx-migration-headline=""
            >
              {fxMigrationHeadline(job)}
            </p>
            {job.progressTotal > 0 && <Progress value={pct} />}
            <p
              className="text-sm tabular-nums text-(--fx-ink-2)"
              aria-live={running ? 'polite' : undefined}
            >
              {fxMigrationLine(job)}
            </p>
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
            <Row
              label="Started"
              value={job.startedAt ? formatDateTime(job.startedAt) : '-'}
            />
            <Row
              label="Finished"
              value={job.finishedAt ? formatDateTime(job.finishedAt) : '-'}
            />
            <Row label="Started by" value={job.actorUserName ?? '-'} />
          </CardContent>
        </Card>
      </div>

      {job.report && (
        <div className="mt-5">
          <MigrationReportCard report={job.report} />
        </div>
      )}

      {canOfferSync(job) && (
        <MigrationSyncCard jobId={job.id} workspaceId={job.workspaceId} />
      )}

      {job.failureCount > 0 && (
        <MigrationFailuresTable
          jobId={job.id}
          rows={job.failureSample}
          totalFailures={job.failureCount}
        />
      )}

      <Card className="mt-5">
        <CardHeader>
          <CardHeading>
            <CardTitle>Logs</CardTitle>
          </CardHeading>
        </CardHeader>
        <CardContent>
          {job.logs.length === 0 ? (
            <p className="text-sm text-(--fx-ink-3)">No log entries yet.</p>
          ) : (
            <ul className="space-y-1.5 font-mono text-xs">
              {job.logs.map((entry, i) => (
                <li key={i} className="flex flex-wrap gap-x-2 gap-y-0.5">
                  <span className="shrink-0 text-(--fx-ink-3)">
                    {formatDateTime(entry.ts)}
                  </span>
                  <span
                    className={
                      entry.level === 'error'
                        ? 'shrink-0 uppercase text-(--fx-act)'
                        : entry.level === 'warning'
                          ? 'shrink-0 uppercase text-(--fx-warn-ink)'
                          : 'shrink-0 uppercase text-(--fx-ink-3)'
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
  );
}
