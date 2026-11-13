'use client';

/**
 * Bulk "Move lifecycle" dialog (AC-CTM-09/31) - a SearchSelect of the
 * workspace's lifecycle stages. Unlike the single-contact "Move to" picker
 * (which lists only THAT contact's fireable edges), a bulk selection can span
 * several current stages, so this offers every stage and lets the machine
 * decide per record - a record with no edge to the target is reported in the
 * per-record failure list (D-A2-5), never silently skipped.
 */
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { SearchSelect } from '@/components/platform/search-select';
import type { LifecycleStageOption } from '@/hooks/use-contact-lifecycle-stages';

export interface BulkLifecycleDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  stages: LifecycleStageOption[];
  count: number;
  onConfirm: (toStatusId: string) => Promise<unknown>;
}

export function BulkLifecycleDialog({ open, onOpenChange, stages, count, onConfirm }: BulkLifecycleDialogProps) {
  const [value, setValue] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const confirm = async () => {
    if (!value) return;
    setBusy(true);
    try {
      await onConfirm(value);
      onOpenChange(false);
      setValue(null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !busy && onOpenChange(v)}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>
            Move lifecycle for {count} contact{count === 1 ? '' : 's'}
          </DialogTitle>
        </DialogHeader>
        <DialogBody>
          <SearchSelect
            ariaLabel="Target lifecycle stage"
            value={value}
            onChange={setValue}
            placeholder="Select a stage…"
            options={stages.map((s) => ({ label: s.label, value: s.id }))}
          />
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button variant="primary" onClick={() => void confirm()} disabled={busy || !value}>
            Move
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
