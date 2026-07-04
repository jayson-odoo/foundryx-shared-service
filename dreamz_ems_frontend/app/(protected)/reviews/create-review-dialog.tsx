'use client';

import { useEffect, useState } from 'react';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { SearchSelect } from '@/components/platform/search-select';
import { formService } from '@/services/form-service';
import { reviewConfigService } from '@/services/review-config-service';
import type { FormRow } from '@/types/forms';

interface Props {
  onClose: () => void;
  onCreated: (id: string) => void;
}

/** Minimal create — name + the two forms (the only server-required fields).
 * Everything else (window, score field, status mapping, roles) is configured on
 * the detail form once the process exists. */
export function CreateReviewDialog({ onClose, onCreated }: Props) {
  const [forms, setForms] = useState<FormRow[]>([]);
  const [name, setName] = useState('');
  const [formId, setFormId] = useState<string | null>(null);
  const [reviewFormId, setReviewFormId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    formService
      .list({ page: 0, pageSize: 200 }) // /forms caps page_size at 200 — >200 → 422
      .then((r) => setForms(r.data))
      .catch(() => setForms([]));
  }, []);

  const options = forms.map((f) => ({ value: f.id, label: f.name }));

  const save = async () => {
    if (!name.trim() || !formId || !reviewFormId) return;
    setBusy(true);
    setError(null);
    try {
      const cfg = await reviewConfigService.create({
        name: name.trim(),
        formId,
        reviewFormId,
      });
      onCreated(cfg.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save.');
      setBusy(false);
    }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>New review process</DialogTitle>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="rc-name">Name *</Label>
            <Input
              id="rc-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
            />
          </div>
          <div className="space-y-1.5">
            <Label>Submission form *</Label>
            <SearchSelect
              value={formId}
              onChange={setFormId}
              options={options}
              ariaLabel="Submission form"
              placeholder="Pick a form…"
            />
          </div>
          <div className="space-y-1.5">
            <Label>Review form *</Label>
            <SearchSelect
              value={reviewFormId}
              onChange={setReviewFormId}
              options={options}
              ariaLabel="Review form"
              placeholder="Pick a form…"
            />
          </div>
          {error && <p className="text-destructive text-sm">{error}</p>}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            onClick={() => void save()}
            disabled={!name.trim() || !formId || !reviewFormId || busy}
          >
            {busy ? 'Saving…' : 'Create'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
