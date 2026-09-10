'use client';

import Link from 'next/link';
import {
  CircleCheck,
  Eye,
  LoaderCircleIcon,
  Pause,
  Play,
  RotateCcw,
  TriangleAlert,
} from 'lucide-react';
import { Alert, AlertDescription, AlertIcon, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardHeading, CardTitle } from '@/components/ui/card';
import { DeferredCountdown } from '@/components/platform/resource-actions/deferred-action-button';
import { PreviewPanel } from '@/components/platform/autocount/preview-panel';
import { useDeferredAction } from '@/hooks/use-deferred-action';
import type {
  UseEtlTaskLifecycleResult,
  UseEtlTaskPreviewResult,
} from '@/hooks/use-autocount-etl';
import { useCan } from '@/hooks/use-can';
import { useDatetime } from '@/hooks/use-datetime';
import {
  activatePrerequisites,
  anchorErrorTitle,
  previewFailedBlocksActivation,
  productDependencyWarning,
} from '@/lib/autocount-etl';
import { toast } from '@/lib/toast';
import type { AutocountCompany, AutocountEntityConfig, AutocountEtlTask } from '@/types/autocount';
import {
  AC_COMPANIES_MANAGE,
  AC_SYNC_RUN,
  acCompanyHref,
  acTaskHref,
} from '../../../../../components/autocount-meta';

/** "Re-push all"'s deferred-action key (sprint-5/07 review round - D2/D13:
 * every destructive action is a no-confirm-dialog grace window on the CORE
 * engine, never a hand-rolled dialog or a component-local timer; registered
 * server-side in `modules/autocount/deferred_actions.py`). */
const REPUSH_ACTION_KEY = 'autocount_etl_task.repush';
const REPUSH_ENTITY_TYPE = 'autocount_etl_task';

export interface ActivateTabProps {
  company: AutocountCompany | null;
  task: AutocountEtlTask;
  /** Unsaved Query/Mapping edits - a preview of an unsaved query proves nothing. */
  configDirty: boolean;
  preview: UseEtlTaskPreviewResult;
  lifecycle: UseEtlTaskLifecycleResult;
  /** A manual run finished - the Runs tab should reload. */
  onRan: () => void;
  /** The company's already-fetched entity list (plan 22 S4, AC-22-23) - lets
   * this tab derive the product/category/UOM dependency heads-up with no
   * extra request. Optional so existing callers are unaffected. */
  entities?: AutocountEntityConfig[];
  /**
   * Re-fetch the TASK ITSELF (status, `nextIncrementalAt`/`nextReconcileAt`)
   * from the server - a re-push arms `nextReconcileAt` to "now" server-side,
   * but the deferred-actions engine's `onCommitted` carries no task payload
   * at all (the commit runs server-side, off the grace window - there is no
   * response for this tab to read). Calling this once the engine reports the
   * commit is the SAME "go get the current task" primitive
   * `useAutocountEtlTask.reload` already provides - foolproof-UI: a badge
   * still showing tonight's 02:00 right after the operator armed an
   * immediate reconcile would be a lie. Optional so existing callers are
   * unaffected.
   */
  reloadTask?: () => void;
}

/**
 * The activate-once gate (plan 22 §3, AC-22-18/19, Appendix A6). Reuses the
 * batch review's dry-run panel in its `task` variant: Run preview → summary +
 * overwrite cards → Activate (withheld until a preview completed); once active
 * the same surface carries Pause / Resume / Run now. Prerequisites the task
 * cannot meet on its own (delivery target, company code) are stated with a
 * link to where they are fixed - never a silent later failure.
 */
export function ActivateTab({
  company,
  task,
  configDirty,
  preview,
  lifecycle,
  onRan,
  entities = [],
  reloadTask = () => {},
}: ActivateTabProps) {
  const { formatDateTime } = useDatetime();
  const { can } = useCan();
  // Backend split (S2 review SHOULD-FIX 7): preview/run are gated
  // `autocount.sync.run` on the server, a DIFFERENT resource than the page's
  // own `autocount.companies.manage` - a user can reach this tab (manage)
  // without being allowed to move data (sync.run). Activate/Pause/Resume
  // stay ungated HERE - they are `companies.manage`, already implied by
  // having reached the page at all.
  const canRun = can(AC_SYNC_RUN);
  const canManage = can(AC_COMPANIES_MANAGE);
  const prerequisites = activatePrerequisites({ company, task, configDirty });
  const blocked = prerequisites.length > 0;
  // A WARNING, never a block (AC-22-23): the retryable/carry-over mechanism
  // makes activating a `product` task before its category/UOM dependency
  // perfectly safe - it just resolves on a later run instead of the next one.
  const dependencyWarning = productDependencyWarning(task.entityType, entities);
  const status = task.etlStatus;
  const busy = lifecycle.busy !== null || preview.state.status === 'loading';
  const previewOk = Boolean(task.lastPreviewAt);

  // "Re-push all" (plan sprint-5/07, AC-07-20..24) - foolproof-UI: only a
  // database task that is actually running (active/paused) can be re-pushed,
  // and only for a viewer who can configure the task at all. A draft or an
  // API-sourced task never offers it, rather than showing it disabled. The
  // deferred-actions engine parks against `ac_entity_config.id` (the ONE
  // per-(company, entityType) task row's own PK) - already on the wire via
  // `entities` (the company-detail entities list, `EntityConfigItem.id`),
  // so no new endpoint/field is needed to reach it from here.
  const currentEntity = entities.find((e) => e.entityType === task.entityType);
  const isDatabaseTask = currentEntity?.sourceImpl === 'sql_db';
  const repushEntityId = currentEntity?.id ?? null;
  const showRepush =
    (status === 'active' || status === 'paused') &&
    isDatabaseTask &&
    canManage &&
    repushEntityId !== null;

  const repush = useDeferredAction({
    // Gated on `showRepush`, not just a non-null id (review round): a
    // viewer who can never fire this action (no `companies.manage`, a
    // draft, or an API-sourced task) must never poll `GET .../current` for
    // it either - the countdown could not be theirs to see.
    watchFromMount: showRepush,
    watch:
      showRepush && repushEntityId
        ? { entityType: REPUSH_ENTITY_TYPE, entityId: repushEntityId }
        : undefined,
    onCommitted: () => {
      // The commit runs server-side, off the grace window - there is no
      // response here to read a real `clearedCount` from (unlike the
      // synchronous API path `EtlService.repush_task` itself answers).
      const tail =
        status === 'active'
          ? ' The full re-push starts on the next scheduler tick.'
          : ' Nothing moves until the task is resumed.';
      toast.success(`Change tracking cleared.${tail}`);
      onRan();
      reloadTask();
    },
    onFailed: (error) => {
      toast.error(error || 'The action failed.', {
        action: (
          <Link href={acTaskHref(task.companyId, task.entityType, 'runs')} className="underline">
            View run
          </Link>
        ),
      });
    },
    // Review round: a Cancel that arrives at/after the window closes loses
    // to the commit (`useDeferredAction.cancel` reconciles by re-reading
    // `current`) and re-parks the countdown SILENTLY otherwise - without
    // this the operator sees the countdown reappear with no explanation for
    // why their Cancel click seemingly did nothing (resource-form.tsx's own
    // gear action wires the exact same toast).
    onCancelFailed: (error) => {
      toast.error(error || 'Could not cancel that action.');
    },
  });
  const repushPending = repush.state.status === 'pending' ? repush.state : null;
  const repushCommitting = repush.state.status === 'committing';

  function startRepush() {
    if (!repushEntityId) return;
    repush
      .start(REPUSH_ACTION_KEY, { entityType: REPUSH_ENTITY_TYPE, entityId: repushEntityId })
      .catch((error: unknown) => {
        toast.error(error instanceof Error ? error.message : 'Could not start that action.');
      });
  }

  // S5 review SHOULD-FIX 4b - SEPARATE from `prerequisites`: that list also
  // gates Run preview, and fixing this means re-running preview after
  // editing the mapping, so Run preview must stay available.
  const previewFailed = previewFailedBlocksActivation(task);

  const previewState = preview.state;
  const hasRun = previewState.status !== 'idle';
  const isLoading = previewState.status === 'loading';
  const dryRunError = previewState.status === 'error' ? previewState.message : null;
  const previewBlock = previewState.status === 'success' ? previewState.preview : null;
  const taskError = previewState.status === 'taskError' ? previewState.error : null;

  async function runNow() {
    const runId = await lifecycle.runNow();
    if (runId) onRan();
  }

  return (
    <div className="flex flex-col gap-4">
      {prerequisites.map((p) => (
        <Alert
          key={p.kind}
          variant="warning"
          appearance="light"
          data-testid={`activate-prerequisite-${p.kind}`}
        >
          <AlertIcon>
            <TriangleAlert />
          </AlertIcon>
          <AlertTitle>
            {p.message}
            {(p.kind === 'sink' || p.kind === 'companyCode') && (
              <>
                {' '}
                <Link href={acCompanyHref(task.companyId)} className="underline">
                  Open company
                </Link>
              </>
            )}
          </AlertTitle>
        </Alert>
      ))}

      {dependencyWarning && (
        <Alert variant="warning" appearance="light" data-testid="activate-dependency-warning">
          <AlertIcon>
            <TriangleAlert />
          </AlertIcon>
          <AlertTitle>{dependencyWarning}</AlertTitle>
        </Alert>
      )}

      {lifecycle.error && (
        <Alert variant="destructive" appearance="light" data-testid="lifecycle-error">
          <AlertIcon>
            <TriangleAlert />
          </AlertIcon>
          <AlertTitle>{lifecycle.error}</AlertTitle>
        </Alert>
      )}

      {task.lastRunError && (
        <Alert variant="destructive" appearance="light" data-testid="task-last-run-error">
          <AlertIcon>
            <TriangleAlert />
          </AlertIcon>
          <AlertTitle>
            {task.lastRunErrorCode ? anchorErrorTitle(task.lastRunErrorCode) : 'Last run failed'}
            {task.lastRunAt ? ` · ${formatDateTime(task.lastRunAt)}` : ''}
          </AlertTitle>
          <AlertDescription>{task.lastRunError}</AlertDescription>
        </Alert>
      )}

      {previewFailed && (
        <Alert variant="destructive" appearance="light" data-testid="etl-preview-failed">
          <AlertIcon>
            <TriangleAlert />
          </AlertIcon>
          <AlertTitle>
            The last preview reported {task.lastPreviewFailedCount} failed row
            {task.lastPreviewFailedCount === 1 ? '' : 's'}.
          </AlertTitle>
          <AlertDescription>
            Fix the mapping, then re-run preview before activating.
          </AlertDescription>
        </Alert>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={blocked || busy || !canRun}
          onClick={() => void preview.run()}
          data-testid="etl-run-preview"
        >
          {isLoading ? (
            <LoaderCircleIcon className="size-4 animate-spin" />
          ) : (
            <Eye className="size-4" />
          )}
          {previewOk ? 'Re-run preview' : 'Run preview'}
        </Button>

        {status === 'draft' && (
          <>
            <Button
              type="button"
              size="sm"
              disabled={blocked || busy || !previewOk || previewFailed}
              onClick={() => void lifecycle.activate()}
              data-testid="etl-activate"
            >
              {lifecycle.busy === 'activate' ? (
                <LoaderCircleIcon className="size-4 animate-spin" />
              ) : (
                <CircleCheck className="size-4" />
              )}
              Activate
            </Button>
          </>
        )}

        {status === 'active' && (
          <>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={busy}
              onClick={() => void lifecycle.pause()}
              data-testid="etl-pause"
            >
              {lifecycle.busy === 'pause' ? (
                <LoaderCircleIcon className="size-4 animate-spin" />
              ) : (
                <Pause className="size-4" />
              )}
              Pause
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={blocked || busy || !canRun}
              onClick={() => void runNow()}
              data-testid="etl-run-now"
            >
              {lifecycle.busy === 'run' ? (
                <LoaderCircleIcon className="size-4 animate-spin" />
              ) : (
                <Play className="size-4" />
              )}
              Run now
            </Button>
          </>
        )}

        {status === 'paused' && (
          <Button
            type="button"
            size="sm"
            disabled={blocked || busy}
            onClick={() => void lifecycle.resume()}
            data-testid="etl-resume"
          >
            {lifecycle.busy === 'resume' ? (
              <LoaderCircleIcon className="size-4 animate-spin" />
            ) : (
              <Play className="size-4" />
            )}
            Resume
          </Button>
        )}

        {showRepush &&
          (repushPending ? (
            <DeferredCountdown
              verb="Re-pushing all"
              commitAt={repushPending.commitAt}
              windowSeconds={repushPending.windowSeconds}
              onCancel={() => void repush.cancel()}
            />
          ) : (
            <Button
              type="button"
              variant="destructive"
              size="sm"
              // `committing` (review round): a SECOND park can succeed
              // server-side the instant the first countdown's window
              // lapses (the beat sweep/lazy-commit claim it before this
              // render even sees the countdown disappear) - disabled here
              // too, not just while another lifecycle action is `busy`.
              disabled={busy || repushCommitting}
              onClick={startRepush}
              data-testid="etl-repush-all"
            >
              <RotateCcw className="size-4" />
              Re-push all
            </Button>
          ))}

        <div className="flex flex-wrap items-center gap-2 sm:ms-auto">
          {task.lastPreviewAt && (
            <Badge variant="success" appearance="light" size="sm" data-testid="etl-preview-passed">
              Preview passed {formatDateTime(task.lastPreviewAt)}
            </Badge>
          )}
          {task.activatedAt && (
            <Badge variant="secondary" appearance="light" size="sm" data-testid="etl-activated-at">
              Activated {formatDateTime(task.activatedAt)}
            </Badge>
          )}
          {task.lastRunAt && !task.lastRunError && (
            <Badge variant="secondary" appearance="light" size="sm" data-testid="etl-last-run-at">
              Last run {formatDateTime(task.lastRunAt)}
            </Badge>
          )}
        </div>
      </div>

      {status === 'active' && (task.nextIncrementalAt || task.nextReconcileAt) && (
        <div className="flex flex-wrap items-center gap-2" data-testid="etl-next-runs">
          {task.nextIncrementalAt && (
            <Badge variant="secondary" appearance="light" size="sm">
              Next incremental {formatDateTime(task.nextIncrementalAt)}
            </Badge>
          )}
          {task.nextReconcileAt && (
            <Badge variant="secondary" appearance="light" size="sm">
              Next reconcile {formatDateTime(task.nextReconcileAt)}
            </Badge>
          )}
        </div>
      )}

      {taskError && (
        <Alert variant="destructive" appearance="light" data-testid="etl-task-error">
          <AlertIcon>
            <TriangleAlert />
          </AlertIcon>
          <AlertTitle>{anchorErrorTitle(taskError.code)}</AlertTitle>
          <AlertDescription>
            {taskError.message}{' '}
            <Link href={acCompanyHref(task.companyId)} className="underline">
              Open company
            </Link>
          </AlertDescription>
        </Alert>
      )}

      {(hasRun || isLoading) && !taskError && (
        <Card>
          <CardHeader>
            <CardHeading>
              <CardTitle>Dry-run preview</CardTitle>
            </CardHeading>
          </CardHeader>
          <CardContent>
            <PreviewPanel
              preview={previewBlock}
              isLoading={isLoading}
              error={dryRunError}
              hasRun={hasRun}
              variant="task"
            />
          </CardContent>
        </Card>
      )}

    </div>
  );
}
