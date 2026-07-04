'use client';

import { Download, FileSpreadsheet, Upload, type LucideIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useImportActivity } from '@/providers/import-activity-provider';
import { useDownloads } from './downloads-manager';
import { useUploadManager } from './upload-manager';

/**
 * App-wide header triggers for the Uploads + Downloads activity drawers
 * (sprint-3/04b). These live next to the profile badge because file transfer is
 * universal — the Drive enqueues them today, but any feature (complaint /
 * invoice attachments, …) can in future. Mounted in the demo1 header; the
 * providers + drawers live at the protected-layout root.
 */
export function ActivityTriggers() {
  const uploads = useUploadManager();
  const downloads = useDownloads();
  const imports = useImportActivity();

  return (
    <>
      <TriggerButton
        icon={Upload}
        label="Uploads"
        count={uploads.activeCount}
        onClick={() => uploads.setOpen(true)}
      />
      <TriggerButton
        icon={FileSpreadsheet}
        label="Imports"
        count={imports.activeCount}
        onClick={() => imports.setDrawerOpen(true)}
      />
      <TriggerButton
        icon={Download}
        label="Downloads"
        count={downloads.activeCount}
        onClick={() => downloads.setOpen(true)}
      />
    </>
  );
}

function TriggerButton({
  icon: Icon,
  label,
  count,
  onClick,
}: {
  icon: LucideIcon;
  label: string;
  count: number;
  onClick: () => void;
}) {
  return (
    <Button
      variant="ghost"
      mode="icon"
      shape="circle"
      aria-label={label}
      onClick={onClick}
      className="relative size-9 hover:bg-primary/10 hover:[&_svg]:text-primary"
    >
      <Icon className="size-4.5!" />
      {count > 0 && (
        <span className="absolute -right-0.5 -top-0.5 flex size-4 items-center justify-center rounded-full bg-primary text-[10px] font-medium text-primary-foreground">
          {count}
        </span>
      )}
    </Button>
  );
}
