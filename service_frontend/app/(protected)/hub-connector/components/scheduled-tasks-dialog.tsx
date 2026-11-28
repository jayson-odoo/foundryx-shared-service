'use client';

import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { ResourceList } from '@/components/platform/resource-list';
import { useScheduledTasksListConfig } from './use-scheduled-tasks-list-config';

export interface ScheduledTasksDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** The Hub Connector's scheduled tasks: last run, last error and Run now. */
export function ScheduledTasksDialog({ open, onOpenChange }: ScheduledTasksDialogProps) {
  const config = useScheduledTasksListConfig();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>Scheduled tasks</DialogTitle>
        </DialogHeader>
        <DialogBody>{open && <ResourceList config={config} hideHeader />}</DialogBody>
      </DialogContent>
    </Dialog>
  );
}
