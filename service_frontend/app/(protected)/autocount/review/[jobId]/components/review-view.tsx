'use client';

import { useState } from 'react';
import Link from 'next/link';
import { ArrowLeft, Check, Eye, LoaderCircleIcon, Trash2 } from 'lucide-react';
import {
  Toolbar,
  ToolbarActions,
  ToolbarHeading,
  ToolbarPageTitle,
} from '@/partials/common/toolbar';
import { Container } from '@/components/common/container';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardHeader,
  CardHeading,
  CardTitle,
} from '@/components/ui/card';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { StatusBadge } from '@/components/platform/status-badge';
import { PreviewPanel } from '@/components/platform/autocount/preview-panel';
import { useDatetime } from '@/hooks/use-datetime';
import { useAutocountReview } from '@/hooks/use-autocount-review';
import { useAutocountPreview } from '@/hooks/use-autocount-preview';
import type { AutocountJobStatus } from '@/types/autocount';
import {
  AC_JOB_STATUS_REGISTRY,
  AC_REVIEW_PATH,
} from '../../../components/autocount-meta';
import { StagedRecordsList } from './staged-records-list';

export interface ReviewViewProps {
  jobId: string;
  /** Where Back returns to - the originating company, when we came from one. */
  from?: string;
}

/**
 * Batch review (AC-13-12) - every staged record's before → after per CHANGED
 * field. Approve pushes to the consumer; Discard closes the batch without
 * pushing. Both are offered only while the job sits in `needs_review`
 * (AC-13-11), and are disabled with a stated reason otherwise.
 */
export function ReviewView({ jobId, from }: ReviewViewProps) {
  const {
    job,
    total,
    noChangeCount,
    isLoading,
    notFound,
    isSubmitting,
    canDecide,
    blockedReason,
    approve,
    discard,
  } = useAutocountReview(jobId);
  const preview = useAutocountPreview(jobId);
  const { formatDateTime } = useDatetime();
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  // Back returns to wherever the operator came from - the originating company
  // when a sync routed them here, otherwise the Review list (its real parent).
  const backHref = from || AC_REVIEW_PATH;

  if (isLoading) {
    return (
      <Container width="fluid">
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <LoaderCircleIcon className="size-6 animate-spin" />
        </div>
      </Container>
    );
  }

  if (notFound || !job) {
    return (
      <Container width="fluid">
        <div className="flex flex-col items-center gap-3 py-24 text-center">
          <p className="text-sm font-medium">Sync batch not found.</p>
          <Button variant="outline" size="sm" asChild>
            <Link href={backHref}>Back</Link>
          </Button>
        </div>
      </Container>
    );
  }

  const changedCount = Math.max(total - noChangeCount, 0);

  return (
    <>
      <Container width="fluid">
        <Toolbar>
          <ToolbarHeading>
            <div className="flex flex-wrap items-center gap-2">
              <Button variant="ghost" size="sm" asChild>
                <Link href={backHref} aria-label="Back">
                  <ArrowLeft className="size-4" />
                </Link>
              </Button>
              <ToolbarPageTitle text="Review batch" />
              <StatusBadge
                status={job.status as AutocountJobStatus}
                registry={AC_JOB_STATUS_REGISTRY}
                size="sm"
              />
            </div>
          </ToolbarHeading>
          <ToolbarActions>
            <div className="flex flex-wrap items-center justify-end gap-2">
              {blockedReason && (
                <span className="text-xs text-muted-foreground">{blockedReason}</span>
              )}
              {preview.failed ? (
                <span className="text-xs text-destructive" data-testid="approve-blocked">
                  Resolve the dry run first
                </span>
              ) : !preview.hasRun ? (
                <span className="text-xs text-muted-foreground" data-testid="approve-blocked">
                  Preview before approving
                </span>
              ) : null}
              <Button
                variant="outline"
                size="sm"
                disabled={!canDecide || isSubmitting || preview.isLoading}
                onClick={() => void preview.run()}
                data-testid="preview-push"
              >
                {preview.isLoading ? (
                  <LoaderCircleIcon className="size-4 animate-spin" />
                ) : (
                  <Eye className="size-4" />
                )}
                Preview push
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={!canDecide || isSubmitting}
                onClick={() => setConfirmDiscard(true)}
                data-testid="discard-batch"
              >
                <Trash2 className="size-4" />
                Discard
              </Button>
              <Button
                size="sm"
                disabled={
                  !canDecide || isSubmitting || preview.isLoading || !preview.hasRun || preview.failed
                }
                onClick={() => void approve()}
                data-testid="approve-batch"
              >
                {isSubmitting ? (
                  <LoaderCircleIcon className="size-4 animate-spin" />
                ) : (
                  <Check className="size-4" />
                )}
                Approve
              </Button>
            </div>
          </ToolbarActions>
        </Toolbar>
      </Container>

      <Container width="fluid">
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground">
            <span>
              {total} record{total === 1 ? '' : 's'} · {changedCount} changed
            </span>
            {job.createdAt && <span>{formatDateTime(job.createdAt)}</span>}
          </div>

          {(preview.hasRun || preview.isLoading) && (
            <Card>
              <CardHeader>
                <CardHeading>
                  <CardTitle>Dry-run preview</CardTitle>
                </CardHeading>
              </CardHeader>
              <CardContent>
                <PreviewPanel
                  preview={preview.preview}
                  isLoading={preview.isLoading}
                  error={preview.error}
                  hasRun={preview.hasRun}
                />
              </CardContent>
            </Card>
          )}

          {total === 0 ? (
            <p className="py-16 text-center text-sm text-muted-foreground">
              No records awaiting review.
            </p>
          ) : (
            <StagedRecordsList jobId={jobId} noChangeCount={noChangeCount} />
          )}
        </div>
      </Container>

      <AlertDialog open={confirmDiscard} onOpenChange={setConfirmDiscard}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Discard this batch?</AlertDialogTitle>
            <AlertDialogDescription>
              Nothing is pushed to the consumer. The records stay on file for audit
              and the next sync re-reads the same window.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={() => void discard()}>Discard</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
