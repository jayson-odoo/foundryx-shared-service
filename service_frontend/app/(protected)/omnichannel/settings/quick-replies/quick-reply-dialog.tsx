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
import { Textarea } from '@/components/ui/textarea';
import type { QuickReply } from '@/types/omnichannel';
import type {
  QuickReplyCreateInput,
  QuickReplyUpdateInput,
} from '@/services/quick-reply-service';

interface QuickReplyDialogProps {
  /** The row being edited, or `null` when creating. */
  item: QuickReply | null;
  onClose: () => void;
  onCreate: (input: QuickReplyCreateInput) => Promise<void>;
  onUpdate: (id: string, input: QuickReplyUpdateInput) => Promise<void>;
}

/**
 * Create / edit a canned response (plan sprint-3/12). Trivial entity → a modal,
 * not a detail page. `body` required; `shortcut` optional (a `/xyz` the composer
 * matches). All mutations go through the parent's hook - no direct service call.
 */
export function QuickReplyDialog({ item, onClose, onCreate, onUpdate }: QuickReplyDialogProps) {
  const editing = item !== null;
  const [shortcut, setShortcut] = useState(item?.shortcut ?? '');
  const [body, setBody] = useState(item?.body ?? '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const valid = body.trim().length > 0;

  const handleSave = async () => {
    if (!valid) return;
    setSaving(true);
    setError(null);
    const trimmedShortcut = shortcut.trim();
    try {
      if (editing) {
        await onUpdate(item.id, {
          shortcut: trimmedShortcut || null,
          body: body.trim(),
        });
      } else {
        await onCreate({ shortcut: trimmedShortcut || null, body: body.trim() });
      }
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save the quick reply.');
      setSaving(false);
    }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{editing ? 'Edit quick reply' : 'New quick reply'}</DialogTitle>
          <DialogDescription>
            A canned response agents insert from the composer.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="qr-shortcut">Shortcut</Label>
            <Input
              id="qr-shortcut"
              value={shortcut}
              placeholder="/greeting"
              onChange={(e) => setShortcut(e.target.value)}
              autoFocus
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="qr-body">
              Message <span className="text-destructive">*</span>
            </Label>
            <Textarea
              id="qr-body"
              value={body}
              rows={4}
              onChange={(e) => setBody(e.target.value)}
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
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
