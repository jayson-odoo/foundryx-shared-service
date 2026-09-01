'use client';

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
import { Label } from '@/components/ui/label';
import { SearchSelect } from '@/components/platform/search-select';
import type { NumberCatalogItem, NumberReset } from '@/types/numbering';
import { NUMBER_RESET_OPTIONS } from '@/types/numbering';

/** Live token substitution for the dialog preview - mirrors the backend tokens. */
function previewNumber(prefix: string, pattern: string, seq: number): string {
  const now = new Date();
  const yyyy = String(now.getFullYear());
  return pattern
    .replace(/\{prefix\}/g, prefix)
    .replace(/\{YYYY\}/g, yyyy)
    .replace(/\{YY\}/g, yyyy.slice(-2))
    .replace(/\{MM\}/g, String(now.getMonth() + 1).padStart(2, '0'))
    .replace(/\{DD\}/g, String(now.getDate()).padStart(2, '0'))
    .replace(/\{(N+)\}/g, (_m, n: string) => String(seq).padStart(n.length, '0'));
}

/**
 * Inline numbering edit dialog (sprint-4/07, Cluster F - AC-07-07). Edits
 * prefix + format + reset + next-val; saving changes the next generated number.
 * Format must contain a running-number token ({NNNN}) - the boundary validates
 * too; here Save is blocked so the user can't submit an always-colliding format.
 */
export function NumberEditDialog({
  item,
  onClose,
  onSave,
}: {
  item: NumberCatalogItem;
  onClose: () => void;
  onSave: (
    docType: string,
    body: { prefix: string; formatPattern: string; reset: NumberReset },
    nextVal: number,
    nextValChanged: boolean,
  ) => Promise<void>;
}) {
  const [prefix, setPrefix] = useState(item.prefix);
  const [formatPattern, setFormatPattern] = useState(item.formatPattern);
  const [reset, setReset] = useState<NumberReset>(item.reset);
  const [nextVal, setNextVal] = useState(String(item.nextVal));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const nextValNum = Number.parseInt(nextVal, 10);
  const hasRunningToken = /\{N+\}/.test(formatPattern);
  const validNextVal = Number.isInteger(nextValNum) && nextValNum >= 1;
  const valid = formatPattern.trim().length > 0 && hasRunningToken && validNextVal;

  const handleSave = async () => {
    if (!valid) return;
    setSaving(true);
    setError(null);
    try {
      await onSave(
        item.docType,
        { prefix: prefix.trim(), formatPattern: formatPattern.trim(), reset },
        nextValNum,
        nextValNum !== item.nextVal,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save.');
      setSaving(false);
    }
  };

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
        <DialogBody className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="num-prefix">Prefix</Label>
            <Input
              id="num-prefix"
              value={prefix}
              onChange={(e) => setPrefix(e.target.value)}
              autoFocus
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="num-format">
              Format pattern <span className="text-destructive">*</span>
              <span className="ms-2 font-normal text-muted-foreground">
                {'{prefix} {YYYY} {YY} {MM} {DD} {NNNN}'}
              </span>
            </Label>
            <Input
              id="num-format"
              className="font-mono"
              value={formatPattern}
              onChange={(e) => setFormatPattern(e.target.value)}
            />
            {!hasRunningToken && formatPattern.trim().length > 0 && (
              <p className="text-destructive text-xs">Include a running-number token like {'{NNNN}'}.</p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label>Reset</Label>
            <SearchSelect
              options={NUMBER_RESET_OPTIONS}
              value={reset}
              onChange={(v) => setReset(v as NumberReset)}
              placeholder="Select reset cadence…"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="num-next">
              Next value <span className="text-destructive">*</span>
            </Label>
            <Input
              id="num-next"
              type="number"
              min={1}
              value={nextVal}
              onChange={(e) => setNextVal(e.target.value)}
            />
          </div>
          <div className="rounded-md bg-muted/50 px-3 py-2">
            <span className="text-xs text-muted-foreground">Preview</span>
            <p className="font-mono text-sm text-foreground">
              {previewNumber(prefix.trim(), formatPattern, validNextVal ? nextValNum : item.nextVal)}
            </p>
          </div>
          {error && <p className="text-destructive text-sm">{error}</p>}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={() => void handleSave()} disabled={!valid || saving}>
            {saving ? 'Saving…' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
