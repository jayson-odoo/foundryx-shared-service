'use client';

import Link from 'next/link';
import {
  CircleCheck,
  Eye,
  LoaderCircleIcon,
  Pause,
  Play,
  TriangleAlert,
} from 'lucide-react';
import { Alert, AlertDescription, AlertIcon, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardHeading, CardTitle } from '@/components/ui/card';
import { PreviewPanel } from '@/components/platform/autocount/preview-panel';
import type {
  UseEtlTaskLifecycleResult,
  UseEtlTaskPreviewResult,
} from '@/hooks/use-autocount-etl';
import { useDatetime } from '@/hooks/use-datetime';
import { activatePrerequisites, anchorErrorTitle } from '@/lib/autocount-etl';
import type { AutocountCompany, AutocountEtlTask } from '@/types/autocount';
import { acCompanyHref } from '../../../../../components/autocount-meta';

export interface ActivateTabProps {
  company: AutocountCompany | null;
  task: AutocountEtlTask;
  /** Unsaved Query/Mapping edits - a preview of an unsaved query proves nothing. */
  configDirty: boolean;
  preview: UseEtlTaskPreviewResult;
  lifecycle: UseEtlTaskLifecycleResult;
  /** A manual run finished - the Runs tab should reload. */
  onRan: () => void;
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
}: ActivateTabProps) {
  const { formatDateTime } = useDatetime();
  const prerequisites = activatePrerequisites({ company, task, configDirty });
  const blocked = prerequisites.length > 0;
  const status = task.etlStatus;
  const busy = lifecycle.busy !== null || preview.state.status === 'loading';
  const previewOk = Boolean(task.lastPreviewAt);

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

      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={blocked || busy}
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
              disabled={blocked || busy || !previewOk}
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
            {!previewOk && !blocked && (
              <span className="text-xs text-muted-foreground" data-testid="activate-blocked">
                Preview before activating
              </span>
            )}
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
              disabled={blocked || busy}
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
