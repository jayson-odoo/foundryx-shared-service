'use client';

import {
  Download,
  FileSpreadsheet,
  Settings2,
  Upload,
  type LucideIcon,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useImportActivity } from '@/providers/import-activity-provider';
import { useJobsActivity } from '@/providers/jobs-activity-provider';
import { useDownloads } from './downloads-manager';
import { useUploadManager } from './upload-manager';

/** Which of the four activity triggers to render (T7 fix round 1) - the
 *  mobile header keeps only Uploads/Downloads (Imports/Jobs stay reachable
 *  via the sidebar drawer's own menu entries, where header width is tight). */
export type ActivityTrigger = 'uploads' | 'imports' | 'jobs' | 'downloads';

const ALL_TRIGGERS: ActivityTrigger[] = ['uploads', 'imports', 'jobs', 'downloads'];

/**
 * App-wide header triggers for the Uploads + Downloads activity drawers
 * (sprint-3/04b). These live next to the profile badge because file transfer is
 * universal - the Drive enqueues them today, but any feature (complaint /
 * invoice attachments, …) can in future. Mounted in the demo1 header; the
 * providers + drawers live at the protected-layout root.
 *
 * `only` narrows which triggers render (default = all four) - extended, not
 * forked, for the mobile header's narrower set (T7 fix round 1, AC-DLA-62
 * carry-over). `compact` sheds the invisible 44px coarse-pointer touch pad
 * (`COARSE_HIT_TARGET_CLASS`, carried by the Button's default size) without
 * changing the visible size - for the same mobile header, now a dense
 * 6-icon cluster where an overlapping touch pad is exactly the case
 * `primitive-classes.ts` documents that class as unsuitable for.
 */
export function ActivityTriggers({
  only = ALL_TRIGGERS,
  compact = false,
}: {
  only?: ActivityTrigger[];
  compact?: boolean;
}) {
  const uploads = useUploadManager();
  const downloads = useDownloads();
  const imports = useImportActivity();
  const jobs = useJobsActivity();
  const show = new Set(only);

  return (
    <>
      {show.has('uploads') && (
        <TriggerButton
          icon={Upload}
          label="Uploads"
          count={uploads.activeCount}
          onClick={() => uploads.setOpen(true)}
          compact={compact}
        />
      )}
      {show.has('imports') && (
        <TriggerButton
          icon={FileSpreadsheet}
          label="Imports"
          count={imports.activeCount}
          onClick={() => imports.setDrawerOpen(true)}
          compact={compact}
        />
      )}
      {show.has('jobs') && (
        <TriggerButton
          icon={Settings2}
          label="Jobs"
          count={jobs.activeCount}
          onClick={() => jobs.setDrawerOpen(true)}
          compact={compact}
        />
      )}
      {show.has('downloads') && (
        <TriggerButton
          icon={Download}
          label="Downloads"
          count={downloads.activeCount}
          onClick={() => downloads.setOpen(true)}
          compact={compact}
        />
      )}
    </>
  );
}

function TriggerButton({
  icon: Icon,
  label,
  count,
  onClick,
  compact = false,
}: {
  icon: LucideIcon;
  label: string;
  count: number;
  onClick: () => void;
  compact?: boolean;
}) {
  return (
    <Button
      variant="ghost"
      mode="icon"
      size={compact ? 'sm' : undefined}
      shape="circle"
      aria-label={label}
      onClick={onClick}
      className="relative size-9 hover:bg-primary/10 hover:[&_svg]:text-primary"
    >
      <Icon className="size-4.5!" />
      {count > 0 && (
        <span className="absolute -right-0.5 -top-0.5 flex size-4 items-center justify-center rounded-full bg-primary text-2xs font-medium text-primary-foreground">
          {count}
        </span>
      )}
    </Button>
  );
}
