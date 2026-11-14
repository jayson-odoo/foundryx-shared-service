'use client';

import { Rocket } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { ClampedText } from '@/components/platform/clamped-text';

export interface BrSendConfirmDialogProps {
  open: boolean;
  repo: string | null;
  ideaCount: number;
  fieldsComplete: { done: number; total: number };
  pending: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

/**
 * Send-to-build confirm (AC-STB-08): a small, plain confirm summarising what
 * will be created. Not destructive, so no typed confirmation.
 */
export function BrSendConfirmDialog({
  open,
  repo,
  ideaCount,
  fieldsComplete,
  pending,
  onCancel,
  onConfirm,
}: BrSendConfirmDialogProps) {
  return (
    <Dialog open={open} onOpenChange={(next) => !next && !pending && onCancel()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Send to build?</DialogTitle>
          <DialogDescription>
            Creates an issue labelled crew-intake and moves this requirement to Sent to build.
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
            <dt className="text-muted-foreground">Repository</dt>
            <dd className="min-w-0 font-medium">
              <ClampedText text={repo ?? ''} lines={1} />
            </dd>
            <dt className="text-muted-foreground">Linked ideas</dt>
            <dd className="font-medium">{ideaCount}</dd>
            <dt className="text-muted-foreground">Fields</dt>
            <dd className="font-medium">
              {fieldsComplete.done} of {fieldsComplete.total} complete
            </dd>
          </dl>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel} disabled={pending}>
            Cancel
          </Button>
          <Button variant="primary" onClick={onConfirm} disabled={pending}>
            <Rocket />
            Send to build
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
