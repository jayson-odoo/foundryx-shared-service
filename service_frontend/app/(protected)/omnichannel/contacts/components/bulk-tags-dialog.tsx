'use client';

/**
 * Bulk "Add tags" / "Remove tags" dialog (AC-CTM-09) - a MultiSelect of the
 * workspace's own tags (foolproof-UI: never a foreign id). `mode` is fixed by
 * which bulk action opened the dialog (two distinct toolbar entries, per
 * AC-CTM-09 - not one dialog with an internal add/remove toggle).
 */
import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { MultiSelect } from '@/components/platform/multi-select';
import type { ContactTag } from '@/types/omnichannel';

export interface BulkTagsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  mode: 'add' | 'remove';
  tags: ContactTag[];
  count: number;
  onConfirm: (mode: 'add' | 'remove', tagIds: string[]) => Promise<unknown>;
}

export function BulkTagsDialog({ open, onOpenChange, mode, tags, count, onConfirm }: BulkTagsDialogProps) {
  const [tagIds, setTagIds] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) setTagIds([]);
  }, [open, mode]);

  const confirm = async () => {
    if (tagIds.length === 0) return;
    setBusy(true);
    try {
      await onConfirm(mode, tagIds);
      onOpenChange(false);
      setTagIds([]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !busy && onOpenChange(v)}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>
            {mode === 'add' ? 'Add tags' : 'Remove tags'} - {count} contact{count === 1 ? '' : 's'}
          </DialogTitle>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-3">
          <MultiSelect
            options={tags.map((t) => ({ label: `${t.emoji ? `${t.emoji} ` : ''}${t.name}`, value: t.id }))}
            value={tagIds}
            onChange={setTagIds}
            placeholder="Select tags…"
          />
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button variant="primary" onClick={() => void confirm()} disabled={busy || tagIds.length === 0}>
            {mode === 'add' ? 'Add' : 'Remove'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
