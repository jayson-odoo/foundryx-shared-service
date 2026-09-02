'use client';

import { LoaderCircleIcon } from 'lucide-react';
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

export interface PublishDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  name: string;
  version: number | null;
  pending: boolean;
  onConfirm: () => void;
}

/**
 * Confirm before repointing `production` to a new version (R4 - publishes
 * are instant and reversible, but they change what the very next
 * `meetings.minutes` job renders). Real dialog, never `confirm()`
 * (CRUD UX standard / feedback_confirm_before_delete_or_unlink).
 */
export function PublishDialog({ open, onOpenChange, name, version, pending, onConfirm }: PublishDialogProps) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            Publish {name} v{version} to production?
          </AlertDialogTitle>
          <AlertDialogDescription>
            The next minutes job for this prompt uses this version immediately. This can be
            reversed by publishing a different version.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction
            onClick={(e) => {
              e.preventDefault();
              onConfirm();
            }}
            disabled={pending}
            data-testid="confirm-publish"
          >
            {pending ? <LoaderCircleIcon className="size-4 animate-spin" /> : 'Publish'}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
