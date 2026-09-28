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
import { Label } from '@/components/ui/label';
import { SearchSelect } from '@/components/platform/search-select';
import type { Idea } from '@/types/ideation';

export interface MergeIdeasDialogProps {
  /** Exactly the rows the caller selected - the ONLY options offered
   * (AC-94-22, owner rule: system dropdown, no default pick). */
  ideas: Idea[];
  onClose: () => void;
  onMerge: (survivorId: string) => Promise<void>;
}

/**
 * The survivor picker (issue #94, ideation round 2, AC-94-22) - a plain
 * `Dialog` + `SearchSelect` over the selected rows, no default pick. Not a
 * confirm dialog (the move is non-destructive and reversible via Unmerge), so
 * the confirm-dialog carve-out rule does not apply.
 */
export function MergeIdeasDialog({ ideas, onClose, onMerge }: MergeIdeasDialogProps) {
  const [survivorId, setSurvivorId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const options = ideas.map((idea) => ({
    label: `${idea.ideaNumber ?? ''} ${idea.title ?? idea.problem}`.trim(),
    value: idea.id,
  }));

  const handleMerge = async () => {
    if (!survivorId) return;
    setSaving(true);
    setError(null);
    try {
      await onMerge(survivorId);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not merge these ideas.');
      setSaving(false);
    }
  };

  return (
    // `modal={false}` - this dialog only ever picks a survivor from the
    // caller's own selection (no other surface interaction matters while it
    // is open), so it does not need Radix's focus-trap/aria-hide-siblings
    // behaviour a true modal gets.
    <Dialog open modal={false} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Merge ideas</DialogTitle>
          <DialogDescription>Choose which idea to keep - the rest fold into it.</DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div className="space-y-1.5">
            <Label>Keep</Label>
            <SearchSelect
              options={options}
              value={survivorId}
              onChange={setSurvivorId}
              placeholder="Select an idea…"
              ariaLabel="Keep"
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={handleMerge} disabled={!survivorId || saving}>
            Merge
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
