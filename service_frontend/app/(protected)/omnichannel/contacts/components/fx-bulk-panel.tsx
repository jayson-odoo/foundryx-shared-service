'use client';

/**
 * Foundryx UIUX switch only (playbook "Changing many at once"): the small
 * panel the three bulk contact changes share. It names the field it changes,
 * holds only that field, and its action says how many contacts it changes
 * ("Update 12 contacts' lifecycle"). The same picker and the same confirm
 * as the switch-off dialogs, so what reaches the server is unchanged.
 */
import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from '@/components/ui/dialog';
import { useHideMainAction } from '@/components/fx/actions/page-actions-context';
import { fxBulkPanelWords, type FxBulkKind } from './contacts-fx';

export interface FxBulkPanelProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  kind: FxBulkKind;
  count: number;
  busy: boolean;
  canSubmit: boolean;
  onSubmit: () => void;
  /** The field's control (named by `fxBulkPanelWords(kind).field`). */
  children: ReactNode;
}

export function FxBulkPanel({
  open,
  onOpenChange,
  kind,
  count,
  busy,
  canSubmit,
  onSubmit,
  children,
}: FxBulkPanelProps) {
  const words = fxBulkPanelWords(kind, count);
  useHideMainAction(open);
  const ready = canSubmit && !busy;
  return (
    <Dialog open={open} onOpenChange={(v) => !busy && onOpenChange(v)}>
      <DialogContent
        data-fx-bulk-panel={kind}
        showCloseButton={false}
        className="max-w-sm gap-3 rounded-(--fx-r-l) border-(--fx-line) bg-(--fx-surface) p-6 text-(--fx-ink) max-sm:w-[calc(100%-32px)]"
      >
        <DialogTitle className="text-lg font-bold text-(--fx-ink)">
          {words.title}
        </DialogTitle>
        <DialogDescription className="sr-only">
          {words.action}
        </DialogDescription>
        <div className="flex flex-col gap-1.5">
          <span
            aria-hidden="true"
            className="text-sm font-semibold text-(--fx-ink-2)"
          >
            {words.field}
          </span>
          {children}
        </div>
        <div className="mt-2 flex flex-wrap items-center justify-end gap-2">
          <Button
            type="button"
            variant="fx-quiet"
            className="h-auto min-h-11 rounded-(--fx-r-pill) px-5"
            onClick={() => onOpenChange(false)}
            disabled={busy}
          >
            Cancel
          </Button>
          <Button
            type="button"
            variant="fx-main"
            className={cn(
              'h-auto min-h-11 rounded-(--fx-r-pill) px-5',
              !ready && 'cursor-not-allowed opacity-45',
            )}
            aria-disabled={ready ? undefined : true}
            onClick={() => {
              if (ready) onSubmit();
            }}
          >
            {words.action}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
