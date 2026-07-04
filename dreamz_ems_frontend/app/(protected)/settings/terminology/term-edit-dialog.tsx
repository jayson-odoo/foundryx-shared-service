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
import type { TermCatalogItem, TermLabels } from '@/types/terminology';

/**
 * Inline rename dialog (plan sprint-3/08 D9). Both singular AND plural required
 * (D3 — no auto-pluralize); Save blocked until both are non-blank.
 */
export function TermEditDialog({
  item,
  onClose,
  onSave,
}: {
  item: TermCatalogItem;
  onClose: () => void;
  onSave: (labels: TermLabels) => Promise<void>;
}) {
  const [singular, setSingular] = useState(item.singular);
  const [plural, setPlural] = useState(item.plural);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const valid = singular.trim().length > 0 && plural.trim().length > 0;

  const handleSave = async () => {
    if (!valid) return;
    setSaving(true);
    setError(null);
    try {
      await onSave({ singular: singular.trim(), plural: plural.trim() });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save.');
      setSaving(false);
    }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Rename “{item.defaultSingular}”</DialogTitle>
          <DialogDescription>
            Default: {item.defaultSingular} / {item.defaultPlural}
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="term-singular">
              Singular <span className="text-destructive">*</span>
            </Label>
            <Input
              id="term-singular"
              value={singular}
              onChange={(e) => setSingular(e.target.value)}
              autoFocus
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="term-plural">
              Plural <span className="text-destructive">*</span>
            </Label>
            <Input
              id="term-plural"
              value={plural}
              onChange={(e) => setPlural(e.target.value)}
            />
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
