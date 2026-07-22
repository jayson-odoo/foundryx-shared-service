'use client';

import { useState } from 'react';
import Link from 'next/link';
import { ArrowLeft, Check, LoaderCircleIcon, Trash2 } from 'lucide-react';
import {
  Toolbar,
  ToolbarActions,
  ToolbarHeading,
  ToolbarPageTitle,
} from '@/partials/common/toolbar';
import { Container } from '@/components/common/container';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
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
import { ClampedText } from '@/components/platform/clamped-text';
import { RecordDiff } from '@/components/platform/autocount/record-diff';
import { diffForDisplay } from '@/lib/autocount-diff';
import { useDatetime } from '@/hooks/use-datetime';
import { useAutocountReview } from '@/hooks/use-autocount-review';
import type {
  AutocountJobStatus,
  AutocountStagedRecord,
  AutocountStagedStatus,
} from '@/types/autocount';
import {
  AC_COMPANIES_PATH,
  AC_JOB_STATUS_REGISTRY,
  AC_STAGED_STATUS_REGISTRY,
  entityLabel,
} from '../../../components/autocount-meta';

function StagedRecordCard({ record }: { record: AutocountStagedRecord }) {
  const view = diffForDisplay(record.diff, record.canonical);
  const failed = record.status === 'FAILED';

  return (
    <Card data-testid={`staged-${record.id}`}>
      <CardHeader className="flex-col items-start gap-2 sm:flex-row sm:items-center sm:justify-between">
        <CardHeading className="min-w-0">
          <CardTitle className="min-w-0">
            <ClampedText
              text={record.docNo || record.sourceRef}
              lines={1}
              className="text-sm font-semibold text-foreground"
            />
          </CardTitle>
          <span className="text-xs text-muted-foreground">
            {entityLabel(record.entityType)}
          </span>
        </CardHeading>
        <div className="flex flex-wrap items-center gap-2">
          {view.isNew && (
            <Badge variant="info" appearance="light" size="sm">
              New record
            </Badge>
          )}
          <StatusBadge
            status={record.status as AutocountStagedStatus}
            registry={AC_STAGED_STATUS_REGISTRY}
            size="sm"
          />
        </div>
      </CardHeader>
      <CardContent>
        {failed ? (
          <div className="flex flex-col gap-2">
            {record.error && (
              <p className="text-sm text-destructive">{record.error}</p>
            )}
            {(record.errors ?? []).map((err, i) => (
              <p key={i} className="text-sm text-destructive">
                {[
                  err.field ? `Field ${err.field}` : null,
                  err.line !== undefined && err.line !== null ? `line ${err.line}` : null,
                  err.message ?? null,
                ]
                  .filter(Boolean)
                  .join(' · ')}
              </p>
            ))}
          </div>
        ) : (
          <RecordDiff diff={record.diff} canonical={record.canonical} />
        )}
      </CardContent>
    </Card>
  );
}

export interface ReviewViewProps {
  jobId: string;
  /** Where Back returns to — the originating company, when we came from one. */
  from?: string;
}

/**
 * Batch review (AC-13-12) — every staged record's before → after per CHANGED
 * field. Approve pushes to the consumer; Discard closes the batch without
 * pushing. Both are offered only while the job sits in `needs_review`
 * (AC-13-11), and are disabled with a stated reason otherwise.
 */
export function ReviewView({ jobId, from }: ReviewViewProps) {
  const {
    job,
    records,
    total,
    isLoading,
    notFound,
    isSubmitting,
    canDecide,
    blockedReason,
    approve,
    discard,
  } = useAutocountReview(jobId);
  const { formatDateTime } = useDatetime();
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const backHref = from || AC_COMPANIES_PATH;

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

  const pending = records.filter((r) => r.status === 'STAGED');

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
                disabled={!canDecide || isSubmitting}
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
              {total} record{total === 1 ? '' : 's'} · {pending.length} awaiting approval
            </span>
            {job.createdAt && <span>{formatDateTime(job.createdAt)}</span>}
          </div>

          {records.length === 0 ? (
            <p className="py-16 text-center text-sm text-muted-foreground">
              No records awaiting review.
            </p>
          ) : (
            records.map((record) => (
              <StagedRecordCard key={record.id} record={record} />
            ))
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
