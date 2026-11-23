'use client';

/**
 * The revoke choice for a key that registered webhook endpoints, with the
 * Foundryx UIUX switch on (slice W2-WS). Same question and the same answer
 * as with the switch off (`onConfirm(pauseEndpoints)`, which parks the
 * deferred revoke): the confirm words and buttons follow the playbook
 * ("Revoke Order sync?", "Keep key" focused, red "Revoke key" with the press
 * and hold from the settings). `FxConfirmDialog` has no slot for the
 * "Also pause them" choice, so its look is repeated here.
 */
import { useEffect, useRef, useState } from 'react';
import { useFxSetting } from '@/hooks/use-fx';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { FxHoldButton } from '@/components/fx/actions/confirm-dialog';
import { useHideMainAction } from '@/components/fx/actions/page-actions-context';
import type { RevokeApiKeyDialogProps } from './revoke-api-key-dialog';

/** "3 webhook endpoints use this key. It stops working at once." */
export function fxRevokeLine(endpointCount: number): string {
  const what =
    endpointCount === 1
      ? '1 webhook endpoint uses'
      : `${endpointCount} webhook endpoints use`;
  return `${what} this key. It stops working at once.`;
}

export function FxRevokeApiKeyDialog({
  keyName,
  endpointCount,
  onConfirm,
  onCancel,
}: RevokeApiKeyDialogProps) {
  const open = keyName !== null;
  const [pause, setPause] = useState(true);
  const [said, setSaid] = useState('');
  const keepRef = useRef<HTMLButtonElement>(null);
  const holdOn = useFxSetting('hold') !== false;
  const holdMs = Number(useFxSetting('hold-time') ?? 3) * 1000;
  useHideMainAction(open);

  useEffect(() => {
    if (open) {
      setPause(true);
      setSaid('');
    }
  }, [open]);

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onCancel()}>
      <DialogContent
        role="alertdialog"
        showCloseButton={false}
        data-fx-confirm=""
        className="max-w-md gap-3 rounded-(--fx-r-l) border-(--fx-line) bg-(--fx-surface) p-6 text-(--fx-ink) max-sm:w-[calc(100%-32px)]"
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          keepRef.current?.focus();
        }}
      >
        <DialogTitle className="line-clamp-2 break-all text-lg font-bold text-(--fx-ink)">
          {`Revoke ${keyName ?? ''}?`}
        </DialogTitle>
        <DialogDescription className="text-sm text-(--fx-ink-2)">
          {fxRevokeLine(endpointCount)}
        </DialogDescription>
        <div className="flex items-center gap-2">
          <Checkbox
            id="fx-revoke-pause-endpoints"
            checked={pause}
            onCheckedChange={(v) => setPause(v === true)}
          />
          <Label
            htmlFor="fx-revoke-pause-endpoints"
            className="text-(--fx-ink)"
          >
            Also pause them
          </Label>
        </div>
        <div className="mt-2 flex flex-nowrap items-start justify-end gap-2">
          <Button
            ref={keepRef}
            type="button"
            variant="fx-quiet"
            className="h-auto min-h-11 rounded-(--fx-r-pill) px-5"
            onClick={onCancel}
          >
            Keep key
          </Button>
          {holdOn ? (
            <FxHoldButton
              label="Revoke key"
              holdMs={holdMs}
              destructive
              onHoldStart={() => setSaid('Hold to confirm')}
              onConfirm={() => onConfirm(pause)}
            />
          ) : (
            <Button
              type="button"
              variant="fx-main"
              className="h-auto min-h-11 rounded-(--fx-r-pill) px-5"
              onClick={() => onConfirm(pause)}
            >
              Revoke key
            </Button>
          )}
        </div>
        <span role="status" aria-live="polite" className="sr-only">
          {said}
        </span>
      </DialogContent>
    </Dialog>
  );
}
