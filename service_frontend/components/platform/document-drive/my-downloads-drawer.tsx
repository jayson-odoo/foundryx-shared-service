'use client';

import { AlertTriangle, Download, Loader2, Package } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import type { DownloadJob } from '@/types/documents';
import { useDownloads } from './downloads-manager';

/** Global right-side drawer for async ZIP downloads, decoupled from the page. */
export function MyDownloadsDrawer() {
  const { jobs, open, setOpen, download } = useDownloads();

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetContent side="right" className="flex w-full flex-col gap-0 p-0 sm:max-w-md">
        <SheetHeader className="border-b px-4 py-3">
          <SheetTitle>My downloads</SheetTitle>
        </SheetHeader>
        <div className="flex-1 overflow-y-auto">
          {jobs.length === 0 ? (
            <p className="p-6 text-center text-sm text-muted-foreground">
              No downloads yet. Select files or a folder and choose “Download as ZIP”.
            </p>
          ) : (
            <ul className="divide-y">
              {jobs.map((job) => (
                <DownloadRow key={job.id} job={job} onDownload={download} />
              ))}
            </ul>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function DownloadRow({
  job,
  onDownload,
}: {
  job: DownloadJob;
  onDownload: (id: string) => Promise<void>;
}) {
  return (
    <li className="flex items-center justify-between gap-2 px-4 py-3">
      <div className="flex min-w-0 items-center gap-2">
        <Package className="size-5 shrink-0 text-muted-foreground" />
        <div className="min-w-0">
          <p className="truncate text-sm font-medium" title={job.filename}>
            {job.filename}
          </p>
          <p className="text-xs text-muted-foreground">
            {job.fileCount} file{job.fileCount === 1 ? '' : 's'} · {label(job)}
          </p>
        </div>
      </div>
      {job.status === 'ready' && (
        <Button size="sm" onClick={() => void onDownload(job.id)}>
          <Download className="size-3.5" /> Download
        </Button>
      )}
      {(job.status === 'pending' || job.status === 'processing') && (
        <Loader2 className="size-4 shrink-0 animate-spin text-muted-foreground" />
      )}
      {job.status === 'failed' && (
        <AlertTriangle className="size-4 shrink-0 text-destructive" />
      )}
    </li>
  );
}

function label(job: DownloadJob): string {
  switch (job.status) {
    case 'pending':
      return 'Queued';
    case 'processing':
      return 'Preparing…';
    case 'ready':
      return 'Ready';
    case 'failed':
      return job.error ?? 'Failed';
    default:
      return job.status;
  }
}
