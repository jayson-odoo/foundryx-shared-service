'use client';

import { use, useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { ArrowLeft, LoaderCircle } from 'lucide-react';
import {
  Toolbar,
  ToolbarActions,
  ToolbarHeading,
  ToolbarPageTitle,
} from '@/partials/common/toolbar';
import { Container } from '@/components/common/container';
import { Card, CardContent, CardHeader, CardHeading, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import { ClampedText } from '@/components/platform/clamped-text';
import {
  JOB_STATUS_LABEL,
  JOB_STATUS_TONE,
  jobProgressPct,
  jobTypeLabel,
} from '@/components/platform/jobs-drawer';
import { useDatetime } from '@/hooks/use-datetime';
import { jobsService } from '@/services/jobs-service';
import { JOB_IN_FLIGHT, type Job, type JobFailure } from '@/types/jobs';
import { useJobActions } from '../use-job-actions';

const POLL_MS = 3000;

/** `/jobs/[id]` detail (sprint-4/10 AC-10-19) — job facts, progress, result
 * failures (for a migration), and the state-aware Abort/Retry/Complete actions.
 * Polls while the job is in flight. */
export default function JobDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { formatDateTime } = useDatetime();
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

  if (notFound) {
    return (
      <Container width="fluid">
        <div className="flex flex-col items-center gap-3 py-24 text-center">
          <p className="text-sm font-medium">Job not found.</p>
          <Button variant="outline" size="sm" asChild>
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

  const failures = (job.result?.failures as JobFailure[] | undefined) ?? [];
  const payload = job.payload ?? {};

  return (
    <Container width="fluid">
      <Toolbar>
        <ToolbarHeading>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" asChild>
              <Link href="/jobs">
                <ArrowLeft className="size-4" />
              </Link>
            </Button>
            <ToolbarPageTitle text={jobTypeLabel(job.type)} />
            <Badge variant={JOB_STATUS_TONE[job.status]} appearance="light">
              {JOB_STATUS_LABEL[job.status]}
            </Badge>
            {JOB_IN_FLIGHT.has(job.status) && (
              <LoaderCircle className="text-muted-foreground size-4 animate-spin" />
            )}
          </div>
        </ToolbarHeading>
        <ToolbarActions>
          <ActionMenu
            actions={actions}
            rows={[job]}
            runtime={{ reload: () => void refresh() }}
            surface="form"
          />
        </ToolbarActions>
      </Toolbar>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardHeading>
              <CardTitle>Progress</CardTitle>
            </CardHeading>
          </CardHeader>
          <CardContent className="space-y-4">
            {job.progressTotal > 0 ? (
              <>
                <Progress value={jobProgressPct(job.progressDone, job.progressTotal)} />
                <div className="flex flex-wrap gap-2">
                  <Badge variant="secondary" appearance="light">
                    {job.progressDone}/{job.progressTotal} copied
                  </Badge>
                  {job.progressFailed > 0 && (
                    <Badge variant="destructive" appearance="light">
                      {job.progressFailed} failed
                    </Badge>
                  )}
                </div>
              </>
            ) : (
              <p className="text-muted-foreground text-sm">Not started yet.</p>
            )}
            {job.error && (
              <ClampedText text={job.error} lines={3} className="text-destructive text-sm" />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardHeading>
              <CardTitle>Details</CardTitle>
            </CardHeading>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <Row label="Type" value={jobTypeLabel(job.type)} />
            <Row label="Status" value={JOB_STATUS_LABEL[job.status]} />
            <Row label="Started" value={job.startedAt ? formatDateTime(job.startedAt) : '—'} />
            <Row label="Finished" value={job.finishedAt ? formatDateTime(job.finishedAt) : '—'} />
            {typeof payload.toConnectionId === 'string' && (
              <Row label="New connection" value={payload.toConnectionId} mono />
            )}
            {typeof payload.fromConnectionId === 'string' && (
              <Row label="Old connection" value={payload.fromConnectionId} mono />
            )}
          </CardContent>
        </Card>
      </div>

      {failures.length > 0 && (
        <Card className="mt-5">
          <CardHeader>
            <CardHeading>
              <CardTitle>Failed assets ({failures.length})</CardTitle>
            </CardHeading>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Key</TableHead>
                    <TableHead>Reason</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {failures.map((f, i) => (
                    <TableRow key={i}>
                      <TableCell className="max-w-xs font-mono text-xs">
                        <ClampedText text={f.key} lines={1} />
                      </TableCell>
                      <TableCell className="text-destructive">
                        <ClampedText text={f.reason} lines={2} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      )}
    </Container>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3 py-1">
      <span className="text-muted-foreground">{label}</span>
      <span className={mono ? 'truncate font-mono text-xs' : 'font-medium'}>{value}</span>
    </div>
  );
}
