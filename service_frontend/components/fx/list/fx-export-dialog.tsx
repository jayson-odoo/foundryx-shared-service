'use client';

/**
 * The export panel with the Foundryx UIUX switch on (owner choice: the gap
 * audit's "Import and export" words). It says what it exports, "12 ticked
 * rows" when rows are ticked, else "All 1,240 matching rows" (never only the
 * loaded page), and its button names the count ("Export 1,240 rows"). The
 * same columns, the same export call and the same CSV as with the switch off.
 * Its button is the dialog's one red action, so the page's hides meanwhile.
 */
import { useState } from 'react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import type { ExportDialogProps } from '@/components/platform/resource-list/export-dialog';
import { useHideMainAction } from '@/components/fx/actions/page-actions-context';
import { FxFileIcon } from '@/components/fx/icons';
import { fxExportLabel, fxExportScope } from './fx-words';

export function FxExportDialog({
  open,
  onOpenChange,
  columns,
  selectedCount,
  totalCount,
  onExport,
}: ExportDialogProps) {
  const [picked, setPicked] = useState<string[]>(() => columns.map((c) => c.id));
  const [busy, setBusy] = useState(false);
  useHideMainAction(open);

  function toggle(id: string) {
    setPicked((prev) => (prev.includes(id) ? prev.filter((c) => c !== id) : [...prev, id]));
  }

  async function handleExport() {
    if (busy || picked.length === 0) return;
    setBusy(true);
    try {
      await onExport(picked.filter((id) => columns.some((c) => c.id === id)));
      onOpenChange(false);
    } finally {
      setBusy(false);
    }
  }

  const known = totalCount !== undefined;
  const scope = known
    ? fxExportScope(selectedCount, totalCount)
    : selectedCount > 0
      ? fxExportScope(selectedCount, 0)
      : 'All matching rows';
  const label = known || selectedCount > 0 ? fxExportLabel(selectedCount, totalCount ?? 0) : 'Export rows';
  const blocked = picked.length === 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        data-fx-export=""
        showCloseButton={false}
        className="max-w-md gap-3 rounded-(--fx-r-l) border-(--fx-line) bg-(--fx-surface) p-6 text-(--fx-ink) max-sm:w-[calc(100%-32px)]"
      >
        <DialogTitle className="text-lg font-bold text-(--fx-ink)">Export to CSV</DialogTitle>
        <DialogDescription className="text-sm text-(--fx-ink-2)" data-fx-export-scope="">
          {scope}
        </DialogDescription>
        <div className="flex max-h-[50vh] flex-col gap-3 overflow-y-auto py-1">
          {columns.map((col) => (
            <div key={col.id} className="flex items-center gap-2.5">
              <Checkbox
                id={`fx-export-${col.id}`}
                checked={picked.includes(col.id)}
                onCheckedChange={() => toggle(col.id)}
              />
              <Label htmlFor={`fx-export-${col.id}`} className="font-normal text-(--fx-ink)">
                {col.label}
              </Label>
            </div>
          ))}
        </div>
        <div className="mt-2 flex flex-nowrap items-start justify-end gap-2">
          <Button
            type="button"
            variant="fx-quiet"
            className="h-auto min-h-11 rounded-(--fx-r-pill) px-5"
            onClick={() => onOpenChange(false)}
          >
            Close
          </Button>
          <div className="relative flex flex-col items-end">
            <Button
              type="button"
              variant="fx-main"
              aria-disabled={blocked || busy ? true : undefined}
              aria-describedby={blocked ? 'fx-export-why' : undefined}
              className={cn('h-auto min-h-11 gap-2 rounded-(--fx-r-pill) px-5', blocked && 'cursor-not-allowed')}
              onClick={() => void handleExport()}
            >
              <FxFileIcon type="CSV" arrow="down" size={18} />
              {label}
            </Button>
            {blocked && (
              <p
                id="fx-export-why"
                className="mt-1 text-end text-sm font-semibold text-[color-mix(in_srgb,var(--fx-act)_82%,var(--fx-surface))]"
              >
                Tick at least one column.
              </p>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
