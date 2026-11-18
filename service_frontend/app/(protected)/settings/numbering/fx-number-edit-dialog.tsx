'use client';

/**
 * The numbering edit dialog with the Foundryx UIUX switch on (slice
 * W4-SETTINGS). The same fields, the same rules and the same save as with
 * the switch off (prefix and format trimmed, the reset cadence, and the next
 * number sent only when it changed); what changes:
 * - The next number is a stepper. It holds whole numbers from 1 up: a typed
 *   decimal is cut to its whole part, exactly as the switch-off dialog reads
 *   it (`parseInt`), so the number shown is the number sent, never a float.
 * - The missing running-number message sits under the format field without
 *   moving anything.
 * - The red action names what it saves: "Save Invoice numbering".
 */
import { useState } from 'react';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { SearchSelect } from '@/components/platform/search-select';
import { FxField, FxFieldMessage, FxStepper } from '@/components/fx/fields';
import type { NumberReset } from '@/types/numbering';
import { NUMBER_RESET_OPTIONS } from '@/types/numbering';
import { previewNumber, type NumberEditDialogProps } from './number-edit-dialog';

export function FxNumberEditDialog({ item, onClose, onSave }: NumberEditDialogProps) {
  const [prefix, setPrefix] = useState(item.prefix);
  const [formatPattern, setFormatPattern] = useState(item.formatPattern);
  const [reset, setReset] = useState<NumberReset>(item.reset);
  const [nextVal, setNextVal] = useState(item.nextVal);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const hasRunningToken = /\{N+\}/.test(formatPattern);
  const valid = formatPattern.trim().length > 0 && hasRunningToken;

  const handleSave = async () => {
    if (!valid) return;
    setSaving(true);
    setError(null);
    try {
      await onSave(
        item.docType,
        { prefix: prefix.trim(), formatPattern: formatPattern.trim(), reset },
        nextVal,
        nextVal !== item.nextVal,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save.');
      setSaving(false);
    }
  };

  const tokenMissing = !hasRunningToken && formatPattern.trim().length > 0;

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Numbering - {item.label}</DialogTitle>
          <DialogDescription>
            Default: {item.defaultPrefix}
            {item.defaultFormat}
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-5">
          <FxField label="Prefix" id="num-prefix">
            <Input
              id="num-prefix"
              value={prefix}
              onChange={(e) => setPrefix(e.target.value)}
              autoFocus
            />
          </FxField>
          <FxField
            label="Format pattern"
            id="num-format"
            message={tokenMissing ? 'Include a running-number token like {NNNN}.' : undefined}
          >
            <Input
              id="num-format"
              className="font-mono"
              aria-invalid={tokenMissing || undefined}
              value={formatPattern}
              onChange={(e) => setFormatPattern(e.target.value)}
            />
          </FxField>
          <FxField label="Reset">
            <SearchSelect
              ariaLabel="Reset"
              options={NUMBER_RESET_OPTIONS}
              value={reset}
              onChange={(v) => setReset(v as NumberReset)}
              placeholder="Select reset cadence…"
            />
          </FxField>
          <FxField label="Next value" id="num-next">
            <FxStepper
              id="num-next"
              value={nextVal}
              onChange={(n) => setNextVal(Math.trunc(n))}
              min={1}
              step={1}
              className="[&_input]:w-20"
            />
          </FxField>
          <div className="rounded-(--fx-r-m) bg-(--fx-surface-2) px-3 py-2">
            <span className="text-xs text-(--fx-ink-3)">Preview</span>
            <p className="font-mono text-sm text-(--fx-ink)">
              {previewNumber(prefix.trim(), formatPattern, nextVal)}
            </p>
          </div>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <div className="relative">
            <Button onClick={() => void handleSave()} disabled={!valid || saving}>
              {saving ? 'Saving…' : `Save ${item.label} numbering`}
            </Button>
            <FxFieldMessage className="end-0 start-auto w-max max-w-64 text-end">{error}</FxFieldMessage>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
