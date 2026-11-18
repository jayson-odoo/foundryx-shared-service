'use client';

/**
 * The close dialog under the Foundryx UIUX switch (W1-CONV). Same steps as
 * today (a required close reason, an optional note, one click to close), the
 * playbook's words: the question names the conversation, the safe button
 * says what it keeps ("Keep it open"), the red action says what it does. The
 * done toast (with Undo) is the pane's job, so this dialog does not toast.
 */
import { useEffect, useState } from 'react';

import { useHideMainAction } from '@/components/fx/actions/page-actions-context';
import { SearchSelect, type SearchSelectOption } from '@/components/platform/search-select';
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
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { ApiError } from '@/lib/api-client';

import type { CloseThreadDialogProps } from '../close-thread-dialog';

const NOTE_MAX = 2000;

/** "Lim Wei Jie's conversation" (pure, tested). */
export function fxConversationOf(name?: string | null): string {
  const n = name?.trim();
  if (!n) return 'this conversation';
  return `${n}${n.endsWith('s') ? "'" : "'s"} conversation`;
}

export function FxCloseThreadDialog({ open, onOpenChange, reasons, onClose, contactName }: CloseThreadDialogProps) {
  const [reasonId, setReasonId] = useState('');
  const [note, setNote] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useHideMainAction(open);

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
      onOpenChange(false);
    } catch (e) {
      if (e instanceof ApiError) {
        const detail = e.detail as { fieldErrors?: Record<string, string>; code?: string; message?: string } | undefined;
        setError(detail?.fieldErrors?.closeReasonId ?? detail?.fieldErrors?.note ?? detail?.message ?? e.message);
      } else {
        setError(e instanceof Error ? e.message : 'Could not close the conversation.');
      }
    } finally {
      setSubmitting(false);
    }
  };

  const subject = fxConversationOf(contactName);
  const title = contactName ? `Close ${subject}?` : 'Close this conversation?';

  return (
    <Dialog open={open} onOpenChange={(v) => !submitting && onOpenChange(v)}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>It leaves the open list until the contact writes again.</DialogDescription>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label>Reason</Label>
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
        <DialogFooter className="items-center gap-2">
          {error && (
            <p role="alert" className="me-auto text-sm text-(--fx-act)">
              {error}
            </p>
          )}
          <Button variant="fx-quiet" className="min-h-11 px-4" onClick={() => onOpenChange(false)} disabled={submitting}>
            Keep it open
          </Button>
          <Button
            variant="fx-main"
            className="min-h-11 px-5"
            onClick={submit}
            disabled={!reasonId || submitting}
            aria-label={contactName ? `Close ${subject}` : 'Close conversation'}
            data-testid="close-thread-submit"
          >
            Close conversation
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
