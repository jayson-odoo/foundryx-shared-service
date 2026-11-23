'use client';

/**
 * A background job's page under the Foundryx UIUX switch (slice W3-JOBS): the
 * same progress, what happened in order, and the files that failed. Its red
 * action follows its state: Stop while it runs, Try again when it failed or
 * needs review; Complete anyway sits beside it as an Other Action.
 *
 * The actions are the job action registry's own (`useJobActions`): Try again
 * runs the registry's `run` (same request, toast and reload as the "…" menu);
 * Stop and Complete anyway park the same deferred action, with the same
 * countdown toast and the same Undo, as the "…" menu does. Polling is today's.
 */
import { use, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { CheckCheck } from 'lucide-react';
import { PageHeader } from '@/components/platform/page-header';
import { Container } from '@/components/common/container';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { ClampedText } from '@/components/platform/clamped-text';
import { runResourceAction } from '@/components/platform/resource-actions/run-action';
import {
  deferredToast,
  dismissDeferredToast,
} from '@/components/platform/resource-actions/deferred-toast';
import type { ResourceAction } from '@/components/platform/resource-list';
import {
  useRegisterMainAction,
  useRegisterOtherActions,
  type FxMainActionSpec,
  type FxOtherActionSpec,
} from '@/components/fx/actions/page-actions-context';
import { FxJobBar, FxJobChip } from '@/components/platform/jobs-drawer/fx-job-chip';
import { fmtCount, jobItem } from '@/components/platform/jobs-drawer/fx-job-items';
import { jobTypeLabel } from '@/components/platform/jobs-drawer';
import { useCan } from '@/hooks/use-can';
import { useDatetime } from '@/hooks/use-datetime';
import { useDeferredAction } from '@/hooks/use-deferred-action';
import { deferredDoneMessage, presentContinuous } from '@/lib/deferred-verb';
import {
  trackPendingEntities,
  untrackPendingEntities,
} from '@/lib/pending-entity-store';
import { toast } from '@/lib/toast';
import { jobsService } from '@/services/jobs-service';
import { JOB_IN_FLIGHT, type Job, type JobFailure, type JobLogEntry } from '@/types/jobs';
import { useJobActions } from '../use-job-actions';
import { FailedAssetsCard } from './failed-assets-card';

const POLL_MS = 3000;

const MAIN_LABEL: Record<string, string> = { abort: 'Stop', retry: 'Try again' };

/** Which registry action is the red one for this job (pure, tested). */
export function jobMainActionId(job: Job): 'abort' | 'retry' | null {
  if (JOB_IN_FLIGHT.has(job.status)) return 'abort';
  if (job.status === 'failed' || job.status === 'needs_review') return 'retry';
  return null;
}

/** Runs the job registry's actions the way the "…" menu does. */
function useRunJobAction(job: Job | null, reload: () => void) {
  const active = useRef<{ ids: string[]; toastId: string; label: string; entityType: string } | null>(
    null,
  );
  const settle = () => {
    const current = active.current;
    if (current) {
      untrackPendingEntities(current.ids);
      dismissDeferredToast(current.toastId);
    }
    active.current = null;
    return current;
  };
  const deferred = useDeferredAction({
    onCommitted: () => {
      const current = settle();
      toast.success(
        current ? deferredDoneMessage(current.label, current.entityType, current.ids.length) : 'Done.',
      );
      reload();
    },
    onFailed: (error) => {
      settle();
      toast.error(error || 'The action failed.');
    },
    onCancelledElsewhere: () => {
      settle();
    },
  });

  return async (action: ResourceAction<Job>) => {
    if (!job) return;
    if (!action.deferred) {
      await runResourceAction(action, [job], { reload });
      return;
    }
    const label = typeof action.label === 'function' ? action.label([job]) : action.label;
    const entityType = action.deferred.entityType;
    const entityIds = [job.id];
    trackPendingEntities(entityIds);
    try {
      const { commitAt, windowSeconds, failedCount, parkedEntityIds } = await deferred.start(
        action.deferred.actionKey,
        entityIds.map((id) => ({ entityType, entityId: id })),
        action.deferred.payload?.([job]),
      );
      untrackPendingEntities(entityIds.filter((id) => !parkedEntityIds.includes(id)));
      const toastId = `pending-action-${entityIds[0]}`;
      active.current = { ids: parkedEntityIds, toastId, label, entityType };
      deferredToast({
        id: toastId,
        verb: presentContinuous(label),
        commitAt,
        windowSeconds,
        fxName: parkedEntityIds.length === 1 ? action.deferred.fxName?.([job]) : undefined,
        onCancel: () => {
          void deferred.cancel();
          untrackPendingEntities(parkedEntityIds);
          dismissDeferredToast(toastId);
          active.current = null;
        },
      });
      if (failedCount > 0) {
        toast.error(
          `Could not start "${label}" on ${failedCount} of ${entityIds.length} - another action may already be pending on it.`,
        );
      }
    } catch (error) {
      untrackPendingEntities(entityIds);
      toast.error(error instanceof Error ? error.message : 'Could not start that action.');
    }
  };
}

export function FxJobDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { formatDateTime } = useDatetime();
  const { can } = useCan();
  const actions = useJobActions();
  const [job, setJob] = useState<Job | null>(null);
  const [notFound, setNotFound] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = useCallback(async () => {
    try {
      setJob(await jobsService.getJob(id));
    } catch {
      setNotFound(true);
    }
  }, [id]);

  // Today's polling: every 3 s while the job is in flight.
  useEffect(() => {
    let active = true;
    const tick = async () => {
      if (!active) return;
      await refresh();
      if (!active) return;
      setJob((cur) => {
        if (cur && JOB_IN_FLIGHT.has(cur.status)) {
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

  const reload = useCallback(() => void refresh(), [refresh]);
  const run = useRunJobAction(job, reload);
  const runRef = useRef(run);
  runRef.current = run;

  // The registry's actions this person may run on this job, as the menu shows them.
  const usable = useMemo(
    () =>
      job
        ? actions.filter(
            (a) =>
              a.surfaces.form &&
              (!a.permission || can(a.permission)) &&
              (a.isVisible ? a.isVisible([job]) : true),
          )
        : [],
    [actions, can, job],
  );
  const mainId = job ? jobMainActionId(job) : null;
  const mainAction = usable.find((a) => a.id === mainId) ?? null;
  const title = job ? jobTypeLabel(job.type) : '';

  const main = useMemo<FxMainActionSpec | null>(
    () =>
      mainAction
        ? {
            id: mainAction.id,
            label: MAIN_LABEL[mainAction.id] ?? String(mainAction.label),
            fullLabel: `${MAIN_LABEL[mainAction.id] ?? String(mainAction.label)} ${title.toLowerCase()}`,
            onClick: () => void runRef.current(mainAction),
          }
        : null,
    [mainAction, title],
  );
  useRegisterMainAction(main);

  const others = useMemo<FxOtherActionSpec[]>(
    () =>
      usable
        .filter((a) => a.id !== mainId)
        .map((a) => ({
          id: a.id,
          label: typeof a.label === 'string' ? a.label : a.label(job ? [job] : []),
          icon: a.id === 'abort' ? 'close' : a.id === 'retry' ? 'refresh' : <CheckCheck />,
          onClick: () => void runRef.current(a),
        })),
    [usable, mainId, job],
  );
  useRegisterOtherActions(others);

  if (notFound) {
    return (
      <Container width="fluid">
        <div className="flex flex-col items-center gap-3 py-24 text-center">
          <p className="text-sm font-semibold text-(--fx-ink)">This job no longer exists</p>
          <Button variant="fx-quiet" size="sm" asChild>
            <Link href="/jobs">Back to jobs</Link>
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

  const item = jobItem(job);
  const failures = (job.result?.failures as JobFailure[] | undefined) ?? [];
  const payload = job.payload ?? {};
  const logs: JobLogEntry[] = job.logs ?? [];
  const running = JOB_IN_FLIGHT.has(job.status);

  return (
    <Container width="fluid">
      <PageHeader
        title={title}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <FxJobChip label={item.status} tone={item.tone} />
            {job.startedAt && <span>Started {formatDateTime(job.startedAt)}</span>}
          </span>
        }
      />

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <section
          aria-labelledby="fx-job-progress"
          className="flex flex-col gap-3 rounded-(--fx-r-l) border border-(--fx-line) bg-(--fx-surface) p-4 sm:p-5"
        >
          <h2 id="fx-job-progress" className="text-base font-semibold text-(--fx-ink)">
            Progress
          </h2>
          {job.progressTotal > 0 ? (
            <>
              <FxJobBar
                pct={Math.min(100, Math.round((job.progressDone / job.progressTotal) * 100))}
                label={`${fmtCount(job.progressDone)} of ${fmtCount(job.progressTotal)}`}
              />
              <p className="text-sm text-(--fx-ink) tabular-nums">
                <span className="font-semibold">
                  {fmtCount(job.progressDone)} of {fmtCount(job.progressTotal)}
                </span>{' '}
                copied
                {job.progressFailed > 0 && (
                  <span className="font-semibold text-(--fx-warn-ink)">
                    {' · '}
                    {fmtCount(job.progressFailed)} failed
                  </span>
                )}
                {running && <span className="text-(--fx-ink-3)"> · still running</span>}
              </p>
            </>
          ) : (
            <p className="text-sm text-(--fx-ink-3)">Not started yet</p>
          )}
          {job.error && <ClampedText text={job.error} lines={3} className="text-sm text-destructive" />}
        </section>

        <section
          aria-labelledby="fx-job-details"
          className="flex flex-col gap-3 rounded-(--fx-r-l) border border-(--fx-line) bg-(--fx-surface) p-4 sm:p-5"
        >
          <h2 id="fx-job-details" className="text-base font-semibold text-(--fx-ink)">
            Details
          </h2>
          <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
            <Fact label="Type" value={title} />
            <Fact label="Status" value={item.status} />
            <Fact label="Started" value={job.startedAt ? formatDateTime(job.startedAt) : '-'} />
            <Fact label="Finished" value={job.finishedAt ? formatDateTime(job.finishedAt) : '-'} />
            {typeof payload.toConnectionId === 'string' && (
              <Fact label="New connection" value={payload.toConnectionId} mono />
            )}
            {typeof payload.fromConnectionId === 'string' && (
              <Fact label="Old connection" value={payload.fromConnectionId} mono />
            )}
          </dl>
        </section>
      </div>

      <section
        aria-labelledby="fx-job-log"
        className="mt-5 flex flex-col gap-3 rounded-(--fx-r-l) border border-(--fx-line) bg-(--fx-surface) p-4 sm:p-5"
      >
        <h2 id="fx-job-log" className="text-base font-semibold text-(--fx-ink)">
          What happened
        </h2>
        {logs.length === 0 ? (
          <p className="text-sm text-(--fx-ink-3)">Nothing yet</p>
        ) : (
          <ol className="flex flex-col gap-2">
            {logs.map((entry, i) => (
              <li key={i} className="grid grid-cols-1 gap-x-3 gap-y-0.5 text-sm sm:grid-cols-[11rem_minmax(0,1fr)]">
                <span className="text-xs text-(--fx-ink-3) tabular-nums sm:text-sm">
                  {formatDateTime(entry.ts)}
                </span>
                <span
                  className={
                    entry.level === 'error'
                      ? 'min-w-0 break-words text-destructive'
                      : entry.level === 'warning'
                        ? 'min-w-0 break-words text-(--fx-warn-ink)'
                        : 'min-w-0 break-words text-(--fx-ink)'
                  }
                >
                  {entry.level !== 'info' && <span className="sr-only">{entry.level}: </span>}
                  {entry.message}
                </span>
              </li>
            ))}
          </ol>
        )}
      </section>

      {failures.length > 0 && <FailedAssetsCard failures={failures} />}
    </Container>
  );
}

function Fact({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <>
      <dt className="text-(--fx-ink-3)">{label}</dt>
      <dd className={mono ? 'min-w-0 truncate font-mono text-xs leading-5 text-(--fx-ink)' : 'min-w-0 font-semibold text-(--fx-ink)'}>
        {value}
      </dd>
    </>
  );
}
