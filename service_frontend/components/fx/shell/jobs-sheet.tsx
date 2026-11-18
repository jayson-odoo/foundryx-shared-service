'use client';

/**
 * One Jobs place (owner choice, gap audit "one Jobs place"): while the
 * Foundryx UIUX switch is on, one Jobs button in the top bar replaces the four
 * Uploads, Imports, Jobs and Downloads buttons, and one sheet shows the four
 * existing lists as tabs.
 *
 * The four drawers' own open flags are the tabs: whatever opened a drawer
 * before (the top bar, an upload starting, a storage migration starting)
 * now opens this sheet on that tab, and the drawers themselves render nothing
 * while the switch is on. The lists are the drawers' own list components, so
 * the rows, links and actions are the same. (Slice W3-JOBS later replaces the
 * tabs with the playbook's single Jobs list.)
 */
import { useEffect, useRef, useState } from 'react';
import { useImportActivity } from '@/providers/import-activity-provider';
import { useJobsActivity } from '@/providers/jobs-activity-provider';
import { Button } from '@/components/ui/button';
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { DownloadsList } from '@/components/platform/document-drive/my-downloads-drawer';
import { useDownloads } from '@/components/platform/document-drive/downloads-manager';
import { UploadsList } from '@/components/platform/document-drive/upload-activity-drawer';
import { useUploadManager } from '@/components/platform/document-drive/upload-manager';
import { ImportsList } from '@/components/platform/import-wizard/imports-drawer';
import { JobsList } from '@/components/platform/jobs-drawer/jobs-drawer';

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

export function FxJobsSheet() {
  const place = useJobsPlace();
  const { flags, setters } = place;
  const [tab, setTab] = useState<FxJobsTab>('jobs');
  const before = useRef<PerTab<boolean>>(flags);

  // A flag that turns on picks its tab; the others turn off, so one tab is
  // ever open and closing the sheet closes them all.
  useEffect(() => {
    const prev = before.current;
    before.current = flags;
    const opened = FX_JOBS_TABS.find(({ tab: t }) => flags[t] && !prev[t]);
    if (!opened) return;
    lastTab = opened.tab;
    setTab(opened.tab);
    for (const { tab: t } of FX_JOBS_TABS) {
      if (t !== opened.tab && flags[t]) setters[t](false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flags.uploads, flags.imports, flags.jobs, flags.downloads]);

  const isOpen = FX_JOBS_TABS.some(({ tab: t }) => flags[t]);
  const close = () => {
    for (const { tab: t } of FX_JOBS_TABS) if (flags[t]) setters[t](false);
  };

  const finished = place.uploads.items.filter(
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
        className="flex w-full flex-col gap-0 border-(--fx-line) bg-(--fx-surface) p-0 text-(--fx-ink) sm:max-w-md"
      >
        <SheetHeader className="border-b border-(--fx-line) px-4 py-3">
          <SheetTitle>Jobs</SheetTitle>
        </SheetHeader>
        <Tabs
          value={tab}
          onValueChange={(value) => setters[value as FxJobsTab](true)}
          className="flex min-h-0 flex-1 flex-col"
        >
          <div className="flex items-center justify-between gap-2 px-4 pt-3">
            <TabsList size="sm" aria-label="Kind of work">
              {FX_JOBS_TABS.map(({ tab: t, label }) => (
                <TabsTrigger key={t} value={t}>
                  {label}
                  {place.counts[t] > 0 && (
                    <span className="text-(--fx-ink-3) tabular-nums">
                      {place.counts[t]}
                    </span>
                  )}
                </TabsTrigger>
              ))}
            </TabsList>
          </div>
          <TabsContent value="uploads" className="flex min-h-0 flex-1 flex-col">
            {finished > 0 && (
              <div className="flex justify-end px-4 pt-2">
                <Button
                  variant="fx-text"
                  size="sm"
                  onClick={place.uploads.clearFinished}
                >
                  Clear finished
                </Button>
              </div>
            )}
            <UploadsList
              items={place.uploads.items}
              onResolve={place.uploads.resolveConflict}
              onRetry={place.uploads.retry}
              onRemove={place.uploads.remove}
            />
          </TabsContent>
          <TabsContent value="imports" className="flex min-h-0 flex-1 flex-col">
            <ImportsList jobs={place.imports.jobs} onNavigate={close} />
          </TabsContent>
          <TabsContent value="jobs" className="flex min-h-0 flex-1 flex-col">
            <JobsList jobs={place.jobs.jobs} onNavigate={close} />
          </TabsContent>
          <TabsContent
            value="downloads"
            className="flex min-h-0 flex-1 flex-col"
          >
            <DownloadsList
              jobs={place.downloads.jobs}
              onDownload={place.downloads.download}
            />
          </TabsContent>
        </Tabs>
      </SheetContent>
    </Sheet>
  );
}
