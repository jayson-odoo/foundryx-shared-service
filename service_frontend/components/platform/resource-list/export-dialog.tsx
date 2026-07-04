'use client';

import { useState } from 'react';
import { Download } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import type { ExportColumn } from './types';

export interface ExportDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  columns: ExportColumn[];
  /** Number of selected rows; 0 means "export the whole filtered set". */
  selectedCount: number;
  onExport: (columnIds: string[]) => Promise<void> | void;
}

export function ExportDialog({
  open,
  onOpenChange,
  columns,
  selectedCount,
  onExport,
}: ExportDialogProps) {
  const [picked, setPicked] = useState<string[]>(() => columns.map((c) => c.id));
  const [busy, setBusy] = useState(false);

  function toggle(id: string) {
    setPicked((prev) => (prev.includes(id) ? prev.filter((c) => c !== id) : [...prev, id]));
  }

  async function handleExport() {
    setBusy(true);
    try {
      await onExport(picked);
      onOpenChange(false);
    } finally {
      setBusy(false);
    }
  }

  const scope =
    selectedCount > 0
      ? `${selectedCount} selected row${selectedCount === 1 ? '' : 's'}`
      : 'all rows matching the current filter';

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Export to CSV</DialogTitle>
          <DialogDescription>Exporting {scope}. Choose the columns to include.</DialogDescription>
        </DialogHeader>
        <DialogBody>
          <div className="flex flex-col gap-3">
            {columns.map((col) => (
              <div key={col.id} className="flex items-center gap-2.5">
                <Checkbox
                  id={`export-${col.id}`}
                  checked={picked.includes(col.id)}
                  onCheckedChange={() => toggle(col.id)}
                />
                <Label htmlFor={`export-${col.id}`} className="font-normal">
                  {col.label}
                </Label>
              </div>
            ))}
          </div>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="primary" onClick={handleExport} disabled={busy || picked.length === 0}>
            <Download /> Export
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
