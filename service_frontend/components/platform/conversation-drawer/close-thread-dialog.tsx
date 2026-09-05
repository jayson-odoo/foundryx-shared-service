'use client';

/**
 * Close dialog (plan 27, AC-IVE-30) - a required active close reason + an
 * optional note (<= 2000 chars). Close stays disabled until a reason is
 * chosen (foolproof-UI - no partial/invalid submit is possible).
 */
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { SearchSelect, type SearchSelectOption } from '@/components/platform/search-select';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { ApiError } from '@/lib/api-client';
import type { CloseReason } from '@/types/omnichannel';

const NOTE_MAX = 2000;

export interface CloseThreadDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  reasons: CloseReason[];
  onClose: (closeReasonId: string, note: string) => Promise<unknown>;
}

export function CloseThreadDialog({ open, onOpenChange, reasons, onClose }: CloseThreadDialogProps) {
  const [reasonId, setReasonId] = useState('');
  const [note, setNote] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setReasonId('');
      setNote('');
      setError(null);
    }
  }, [open]);

  const options: SearchSelectOption[] = reasons
    .filter((r) => r.isActive)
    .sort((a, b) => a.sortOrder - b.sortOrder)
    .map((r) => ({ label: r.name, value: r.id }));

  const submit = async () => {
    if (!reasonId) return;
    setSubmitting(true);
    setError(null);
    try {
      await onClose(reasonId, note.trim());
      toast.success('Conversation closed.');
      onOpenChange(false);
    } catch (e) {
      if (e instanceof ApiError) {
        const fieldErrors = (e.detail as { fieldErrors?: Record<string, string> } | undefined)?.fieldErrors;
        setError(fieldErrors?.closeReasonId ?? fieldErrors?.note ?? e.message);
      } else {
        setError(e instanceof Error ? e.message : 'Could not close the conversation.');
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !submitting && onOpenChange(v)}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>Close conversation</DialogTitle>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-4">
          {error && <p className="text-sm text-destructive">{error}</p>}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="close-reason">Reason</Label>
            <SearchSelect
              options={options}
              value={reasonId || null}
              onChange={setReasonId}
              placeholder="Choose a reason"
              ariaLabel="Close reason"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="close-note">Note</Label>
            <Textarea
              id="close-note"
              rows={3}
              maxLength={NOTE_MAX}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              data-testid="close-note"
            />
          </div>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            disabled={!reasonId || submitting}
            data-testid="close-thread-submit"
          >
            Close conversation
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
