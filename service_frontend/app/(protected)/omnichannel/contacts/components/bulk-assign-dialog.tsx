'use client';

/**
 * Bulk "Assign" dialog (AC-CTM-09) - a SearchSelect of the workspace's
 * members plus an explicit "Unassigned" option (foolproof-UI: only valid
 * choices, never a bare text field for a user id).
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
import type { WorkspaceMember } from '@/types/omnichannel';

const UNASSIGNED = '__unassigned__';

export interface BulkAssignDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  members: WorkspaceMember[];
  count: number;
  onConfirm: (assigneeUserId: string | null) => Promise<unknown>;
}

export function BulkAssignDialog({ open, onOpenChange, members, count, onConfirm }: BulkAssignDialogProps) {
  const [value, setValue] = useState<string>(UNASSIGNED);
  const [busy, setBusy] = useState(false);

  const confirm = async () => {
    setBusy(true);
    try {
      await onConfirm(value === UNASSIGNED ? null : value);
      onOpenChange(false);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !busy && onOpenChange(v)}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>
            Assign {count} contact{count === 1 ? '' : 's'}
          </DialogTitle>
        </DialogHeader>
        <DialogBody>
          <SearchSelect
            ariaLabel="Assignee"
            value={value}
            onChange={setValue}
            options={[
              { label: 'Unassigned', value: UNASSIGNED },
              ...members.map((m) => ({ label: m.name ?? m.email, value: m.userId })),
            ]}
          />
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button variant="primary" onClick={() => void confirm()} disabled={busy}>
            Assign
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
