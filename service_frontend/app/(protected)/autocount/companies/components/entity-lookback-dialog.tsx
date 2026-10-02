'use client';

import { useEffect, useState } from 'react';
import { LoaderCircleIcon } from 'lucide-react';
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
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useDatetime } from '@/hooks/use-datetime';
import type { AutocountEntityConfig } from '@/types/autocount';
import { entityLabel } from '../../components/autocount-meta';

/** Session-timezone rendering of a backend timestamp - never `new Date(iso)`. */
function SyncPosition({ iso }: { iso: string }) {
  const { formatDateTime } = useDatetime();
  return <>{formatDateTime(iso)}</>;
}

/** Mirrors the backend bound (`MIN_LOOKBACK_DAYS`/`MAX_LOOKBACK_DAYS`). The
 * server is the real boundary; this stops a guaranteed 422 at the input. */
const MIN_DAYS = 1;
const MAX_DAYS = 3650;

export interface EntityLookbackDialogProps {
  entity: AutocountEntityConfig | null;
  onClose: () => void;
  onSave: (entityType: string, days: number) => Promise<void>;
}

/**
 * Edit an entity's first-run window.
 *
 * Why editable at all: `initialLookbackDays` defaults to 30, so a newly
 * connected company only ever sees the last 30 days and a customer's whole
 * back-catalogue is invisible with no operator remedy. This is the cheap escape
 * hatch - widen the first window once and the history comes in. The supervised
 * full initial-load reconciliation remains D20 / slice 3 and is NOT this.
 *
 * The "first run only" semantics are conveyed as STATE, not as instructional
 * copy: when the entity already has a sync position that position is shown and
 * the input is disabled, so the field visibly cannot re-widen an established
 * window. The one-line description says what the field IS, not how to use it.
 */
export function EntityLookbackDialog({
  entity,
  onClose,
  onSave,
}: EntityLookbackDialogProps) {
  const [value, setValue] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (entity) setValue(String(entity.initialLookbackDays));
  }, [entity]);

  // Once a sync position exists the watermark wins - the backend's
  // `Watermark.start()` returns it and ignores the lookback entirely. Offering
  // an edit that provably does nothing is exactly the foolproof-UI violation
  // ("only offer valid options"), so the field is locked and the established
  // position is shown in its place.
  const superseded = Boolean(entity?.watermarkAt);

  const parsed = Number(value);
  const valid =
    !superseded &&
    value.trim() !== '' &&
    Number.isInteger(parsed) &&
    parsed >= MIN_DAYS &&
    parsed <= MAX_DAYS;

  async function submit() {
    if (!entity || !valid) return;
    setSaving(true);
    try {
      await onSave(entity.entityType, parsed);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={Boolean(entity)} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            First-run window{entity ? ` - ${entityLabel(entity.entityType)}` : ''}
          </DialogTitle>
          <DialogDescription>
            Days of history the first sync fetches.
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-2">
              <Label htmlFor="ac-lookback-days">Days</Label>
              <Input
                id="ac-lookback-days"
                type="number"
                min={MIN_DAYS}
                max={MAX_DAYS}
                step={1}
                value={value}
                disabled={superseded}
                onChange={(event) => setValue(event.target.value)}
                data-testid="lookback-days"
              />
              {!superseded && !valid && value.trim() !== '' && (
                <span className="text-xs text-destructive" data-testid="lookback-error">
                  Enter a whole number between {MIN_DAYS} and {MAX_DAYS}.
                </span>
              )}
            </div>
            {superseded && entity?.watermarkAt && (
              <div
                className="flex flex-col gap-1 rounded-md bg-muted p-3"
                data-testid="lookback-superseded"
              >
                <span className="text-xs text-muted-foreground">Sync position</span>
                <span className="text-sm text-foreground">
                  <SyncPosition iso={entity.watermarkAt} />
                </span>
              </div>
            )}
          </div>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={!valid || saving} data-testid="save-lookback">
            {saving && <LoaderCircleIcon className="size-4 animate-spin" />}
            Save lookback
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
