'use client';

/**
 * One Jobs place (owner choice, gap audit "one Jobs place"): while the
 * Foundryx UIUX switch is on, one Jobs button in the top bar replaces the four
 * Uploads, Imports, Jobs and Downloads buttons, and one sheet lists all four
 * kinds of work as jobs, newest first (slice W3-JOBS): what it is and for
 * what, a status chip, real progress while it runs and its next step.
 *
 * The four drawers' own open flags still open it: whatever opened a drawer
 * before (the top bar, an upload starting, a ZIP being requested, a storage
 * migration starting) now opens this sheet, and the drawers themselves render
 * nothing while the switch is on. Opening the sheet also raises the downloads
 * flag, which is what loads the downloads list today. Every row action calls
 * the provider function the old drawer row called, so the requests are the
 * same. When a job ends, a toast says what finished and how it went, on
 * whatever page the user is on.
 */
import { useEffect, useMemo, useRef } from 'react';
import Link from 'next/link';
import { toast } from '@/lib/toast';
import { useImportActivity } from '@/providers/import-activity-provider';
import { useJobsActivity } from '@/providers/jobs-activity-provider';
import { Button } from '@/components/ui/button';
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { useDownloads } from '@/components/platform/document-drive/downloads-manager';
import { formatBytes } from '@/components/platform/document-drive/lib';
import { useUploadManager } from '@/components/platform/document-drive/upload-manager';
import { FxJobsList } from '@/components/platform/jobs-drawer/fx-jobs-list';
import {
  endToast,
  toJobItems,
  type FxJobItem,
} from '@/components/platform/jobs-drawer/fx-job-items';

export type FxJobsTab = 'uploads' | 'imports' | 'jobs' | 'downloads';

export const FX_JOBS_TABS: { tab: FxJobsTab; label: string }[] = [
  { tab: 'uploads', label: 'Uploads' },
  { tab: 'imports', label: 'Imports' },
  { tab: 'jobs', label: 'Jobs' },
  { tab: 'downloads', label: 'Downloads' },
];

type PerTab<V> = Record<FxJobsTab, V>;

/** The tab the Jobs button opens: the last one used, else the first with work
 *  running, else Jobs. */
export function pickJobsTab(
  counts: PerTab<number>,
  last: FxJobsTab | null,
): FxJobsTab {
  if (last) return last;
  return FX_JOBS_TABS.find(({ tab }) => counts[tab] > 0)?.tab ?? 'jobs';
}

// The last tab shown, for this page session (the button reopens it).
let lastTab: FxJobsTab | null = null;

/** Test helper. */
export function resetJobsSheetForTests(): void {
  lastTab = null;
}

/** The four activity sources as one place: open flags, setters, counts. */
export function useJobsPlace() {
  const uploads = useUploadManager();
  const downloads = useDownloads();
  const imports = useImportActivity();
  const jobs = useJobsActivity();

  const flags: PerTab<boolean> = {
    uploads: uploads.open,
    imports: imports.drawerOpen,
    jobs: jobs.drawerOpen,
    downloads: downloads.open,
  };
  const setters: PerTab<(open: boolean) => void> = {
    uploads: uploads.setOpen,
    imports: imports.setDrawerOpen,
    jobs: jobs.setDrawerOpen,
    downloads: downloads.setOpen,
  };
  const counts: PerTab<number> = {
    uploads: uploads.activeCount,
    imports: imports.activeCount,
    jobs: jobs.activeCount,
    downloads: downloads.activeCount,
  };
  const total =
    counts.uploads + counts.imports + counts.jobs + counts.downloads;

  /** Opens the sheet on `tab` (default: see `pickJobsTab`). */
  const open = (tab?: FxJobsTab) => {
    setters[tab ?? pickJobsTab(counts, lastTab)](true);
  };

  return { flags, setters, counts, total, open, uploads, downloads, imports, jobs };
}

/** Whether a change from `before` to `after` ends the job (and toasts). */
export function jobJustEnded(before: FxJobItem | undefined, after: FxJobItem): boolean {
  if (!before) return false;
  if (after.phase === 'ended') return before.phase !== 'ended';
  // A background job that stops to wait for review has ended its run.
  return after.kind === 'job' && before.phase === 'running' && after.phase === 'waiting';
}

/** Toasts each job that ends while the app is open (not the ones already
 *  over when the list first loads). */
function useJobEndToasts(items: FxJobItem[]): void {
  const seen = useRef<Map<string, FxJobItem> | null>(null);
  useEffect(() => {
    const prev = seen.current;
    const next = new Map(items.map((item) => [item.key, item]));
    seen.current = next;
    if (!prev) return;
    for (const item of items) {
      if (!jobJustEnded(prev.get(item.key), item)) continue;
      const words = endToast(item);
      if (words) toast.fxDone(words);
    }
  }, [items]);
}

export function FxJobsSheet() {
  const place = useJobsPlace();
  const { flags, setters } = place;

  const isOpen = FX_JOBS_TABS.some(({ tab: t }) => flags[t]);
  const close = () => {
    for (const { tab: t } of FX_JOBS_TABS) if (flags[t]) setters[t](false);
  };

  // Opening the sheet raises the downloads flag too: that is what loads the
  // downloads list (the provider loads it when its drawer opens).
  const wasOpen = useRef(false);
  useEffect(() => {
    if (isOpen && !wasOpen.current) {
      const opened = FX_JOBS_TABS.find(({ tab: t }) => flags[t]);
      if (opened) lastTab = opened.tab;
      if (!flags.downloads) setters.downloads(true);
    }
    wasOpen.current = isOpen;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  const uploads = place.uploads.items;
  const imports = place.imports.jobs;
  const jobs = place.jobs.jobs;
  const downloads = place.downloads.jobs;
  const items = useMemo(
    () => toJobItems({ uploads, imports, jobs, downloads, sizeOf: formatBytes }),
    [uploads, imports, jobs, downloads],
  );
  useJobEndToasts(items);

  const finished = uploads.filter(
    (it) => it.status === 'done' || it.status === 'failed',
  ).length;

  return (
    <Sheet
      open={isOpen}
      onOpenChange={(next) => {
        if (!next) close();
      }}
    >
      <SheetContent
        side="right"
        aria-describedby={undefined}
        className="flex w-full flex-col gap-0 border-(--fx-line) bg-(--fx-surface) p-0 text-(--fx-ink) sm:max-w-md"
      >
        <SheetHeader className="flex-row items-center justify-between gap-2 border-b border-(--fx-line) px-4 py-3 pe-12">
          <SheetTitle>Jobs</SheetTitle>
          <div className="flex items-center gap-1">
            {finished > 0 && (
              <Button
                variant="fx-text"
                size="sm"
                onClick={place.uploads.clearFinished}
              >
                Clear finished uploads
              </Button>
            )}
            <Button variant="fx-text" size="sm" asChild>
              <Link href="/jobs" onClick={close}>
                All jobs
              </Link>
            </Button>
          </div>
        </SheetHeader>
        <FxJobsList
          items={items}
          handlers={{
            onNavigate: close,
            onDownload: (id) => void place.downloads.download(id),
            onRetryUpload: place.uploads.retry,
            onResolveUpload: place.uploads.resolveConflict,
            onRemoveUpload: place.uploads.remove,
          }}
        />
      </SheetContent>
    </Sheet>
  );
}
