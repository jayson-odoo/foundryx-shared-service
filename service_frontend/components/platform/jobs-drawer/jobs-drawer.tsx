'use client';

import { useRouter } from 'next/navigation';
import { CheckCircle2, CircleAlert, Loader2, Settings2, XCircle } from 'lucide-react';
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { ClampedText } from '@/components/platform/clamped-text';
import { useDatetime } from '@/hooks/use-datetime';
import { JOB_IN_FLIGHT, type Job } from '@/types/jobs';
import {
  JOB_STATUS_LABEL,
  JOB_STATUS_TONE,
  jobProgressPct,
  jobTypeLabel,
} from './job-display';

export interface JobsDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  jobs: Job[];
}

/**
 * Generic, type-aware background-jobs activity drawer (sprint-4/10 AC-10-19) -
 * a sibling of the Uploads/Downloads/Imports drawers, triggered from the header.
 * Storage migration is the first `type`; the drawer renders any job's type +
 * status + progress. Click a job → its detail page. Poll/refresh is owned by the
 * provider; this is presentational.
 */
export function JobsDrawer({ open, onOpenChange, jobs }: JobsDrawerProps) {
  const router = useRouter();

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex w-full flex-col gap-0 p-0 sm:max-w-md">
        <SheetHeader className="border-b px-4 py-3">
          <SheetTitle>Jobs</SheetTitle>
        </SheetHeader>
        <div className="flex-1 overflow-y-auto">
          {jobs.length === 0 ? (
            <p className="text-muted-foreground p-6 text-center text-sm">
              No background jobs yet.
            </p>
          ) : (
            <ul className="divide-y">
              {jobs.map((job) => (
                <li
                  key={job.id}
                  className="hover:bg-accent flex cursor-pointer items-start gap-3 px-4 py-3"
                  onClick={() => {
                    onOpenChange(false);
                    router.push(`/jobs/${job.id}`);
                  }}
                >
                  <Settings2 className="text-muted-foreground mt-0.5 size-5 shrink-0" />
                  <JobRow job={job} />
                  <StatusIcon job={job} />
                </li>
              ))}
            </ul>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function JobRow({ job }: { job: Job }) {
  const { formatDateTime } = useDatetime();
  const inFlight = JOB_IN_FLIGHT.has(job.status);
  const pct = jobProgressPct(job.progressDone, job.progressTotal);

  return (
    <div className="min-w-0 flex-1">
      <div className="flex items-center gap-2">
        <p className="truncate text-sm font-medium">{jobTypeLabel(job.type)}</p>
        <Badge variant={JOB_STATUS_TONE[job.status]} appearance="light" size="sm">
          {JOB_STATUS_LABEL[job.status]}
        </Badge>
      </div>
      {inFlight && job.progressTotal > 0 && (
        <Progress value={pct} className="mt-2 h-1.5" />
      )}
      <p className="text-muted-foreground mt-1 text-xs">
        {job.progressTotal > 0
          ? `${job.progressDone}/${job.progressTotal} copied${
              job.progressFailed ? ` · ${job.progressFailed} failed` : ''
            }`
          : formatDateTime(job.createdAt)}
      </p>
      {job.error && (
        <ClampedText text={job.error} lines={1} className="text-destructive mt-1 text-xs" />
      )}
    </div>
  );
}

function StatusIcon({ job }: { job: Job }) {
  if (JOB_IN_FLIGHT.has(job.status)) {
    return <Loader2 className="text-muted-foreground mt-0.5 size-4 shrink-0 animate-spin" />;
  }
  if (job.status === 'done') {
    return <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-green-600" />;
  }
  if (job.status === 'failed') {
    return <XCircle className="text-destructive mt-0.5 size-4 shrink-0" />;
  }
  if (job.status === 'needs_review') {
    return <CircleAlert className="mt-0.5 size-4 shrink-0 text-yellow-600" />;
  }
  return null;
}
