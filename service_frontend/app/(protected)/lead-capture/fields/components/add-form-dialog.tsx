'use client';

import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { SearchSelect } from '@/components/platform/search-select';
import { isFormId } from '@/lib/lead-field-map';
import type { LeadSourceItem } from '@/types/lead-capture';
import type { MapTarget } from './map-fields-dialog';

export interface AddFormDialogProps {
  open: boolean;
  sources: LeadSourceItem[];
  onOpenChange: (open: boolean) => void;
  /** Hands the chosen Page + form to the Map fields popup. */
  onPick: (target: MapTarget) => void;
}

/** Pick the Page and enter the Instant Form id; the map popup loads its questions. */
export function AddFormDialog({ open, sources, onOpenChange, onPick }: AddFormDialogProps) {
  const [sourceId, setSourceId] = useState('');
  const [formId, setFormId] = useState('');
  const [touched, setTouched] = useState(false);

  useEffect(() => {
    if (open) {
      setSourceId(sources.length === 1 ? sources[0].id : '');
      setFormId('');
      setTouched(false);
    }
  }, [open, sources]);

  const formOk = isFormId(formId);
  const ready = sourceId !== '' && formOk;

  const submit = () => {
    setTouched(true);
    if (!ready) return;
    const id = formId.trim();
    onOpenChange(false);
    onPick({ sourceId, formId: id, formName: `Instant Form ${id}` });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Add form</DialogTitle>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-4">
          {sources.length === 0 && (
            <p className="text-sm text-destructive">No Facebook Page is connected yet.</p>
          )}
          <div className="flex flex-col gap-2">
            <Label>Page *</Label>
            <SearchSelect
              ariaLabel="Page"
              options={sources.map((s) => ({ value: s.id, label: s.pageName || s.name }))}
              value={sourceId}
              onChange={setSourceId}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="lead-form-id">Instant Form ID *</Label>
            <Input
              id="lead-form-id"
              inputMode="numeric"
              maxLength={64}
              value={formId}
              aria-invalid={touched && !formOk ? true : undefined}
              onChange={(e) => setFormId(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  submit();
                }
              }}
            />
            {touched && !formOk && <p className="text-sm text-destructive">Enter the Instant Form ID (digits only).</p>}
          </div>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="primary" onClick={submit} disabled={sourceId === '' || formId.trim() === ''}>
            Next
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
