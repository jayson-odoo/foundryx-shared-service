'use client';

import { useRouter } from 'next/navigation';
import { CheckCircle2, FileSpreadsheet, Loader2, XCircle } from 'lucide-react';
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { Badge } from '@/components/ui/badge';
import { useImportActivity } from '@/providers/import-activity-provider';
import { useDatetime } from '@/hooks/use-datetime';
import type { ImportJob } from '@/types/import';

const IN_FLIGHT = new Set(['pending', 'validating', 'importing']);

/** Global right-side drawer for import jobs (sprint-3/09 D9) - sibling of the
 * Uploads/Downloads drawers, triggered from the header. Click a job → its page. */
export function ImportsDrawer() {
  const { jobs, drawerOpen, setDrawerOpen } = useImportActivity();
  const router = useRouter();
  const { formatDateTime } = useDatetime();

  return (
    <Sheet open={drawerOpen} onOpenChange={setDrawerOpen}>
      <SheetContent side="right" className="flex w-full flex-col gap-0 p-0 sm:max-w-md">
        <SheetHeader className="border-b px-4 py-3">
          <SheetTitle>Imports</SheetTitle>
        </SheetHeader>
        <div className="flex-1 overflow-y-auto">
          {jobs.length === 0 ? (
            <p className="text-muted-foreground p-6 text-center text-sm">
              No imports yet. Use Import on any list to bring data in.
            </p>
          ) : (
            <ul className="divide-y">
              {jobs.map((job) => (
                <li
                  key={job.id}
                  className="hover:bg-accent flex cursor-pointer items-center gap-3 px-4 py-3"
                  onClick={() => {
                    setDrawerOpen(false);
                    router.push(`/imports/${job.id}`);
                  }}
                >
                  <FileSpreadsheet className="text-muted-foreground size-5 shrink-0" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{job.entityType}</p>
                    <p className="text-muted-foreground text-xs">
                      {job.status === 'done'
                        ? `${job.createdIds?.length ?? 0} created${job.updatedIds?.length ? `, ${job.updatedIds.length} updated` : ''}`
                        : `${job.validRows}/${job.totalRows} rows · ${formatDateTime(job.createdAt)}`}
                    </p>
                  </div>
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

function StatusIcon({ job }: { job: ImportJob }) {
  if (IN_FLIGHT.has(job.status)) {
    return <Loader2 className="text-muted-foreground size-4 shrink-0 animate-spin" />;
  }
  if (job.status === 'done') {
    return <CheckCircle2 className="size-4 shrink-0 text-green-600" />;
  }
  if (job.status === 'failed') {
    return <XCircle className="text-destructive size-4 shrink-0" />;
  }
  return (
    <Badge variant="secondary" appearance="light" size="sm">
      {job.status}
    </Badge>
  );
}
