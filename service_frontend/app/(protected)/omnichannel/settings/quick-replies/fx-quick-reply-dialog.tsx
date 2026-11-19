'use client';

/**
 * The quick reply dialog with the Foundryx UIUX switch on (slice W2-WS).
 * Same fields and the same save as with the switch off (`onCreate` /
 * `onUpdate` with the trimmed shortcut, or null, and the trimmed message);
 * what changes is how it looks and reads: the red action names the shortcut
 * ("Create /greeting quick reply"), is greyed with its reason while the
 * message is empty, and a refused save says why under it.
 */
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import {
  FxActionError,
  useFxActionError,
} from '@/components/fx/actions/action-error';
import { FxMainAction } from '@/components/fx/actions/main-action';
import { useHideMainAction } from '@/components/fx/actions/page-actions-context';
import type { QuickReplyDialogProps } from './quick-reply-dialog';

const LABEL = 'text-sm font-semibold text-(--fx-ink-2)';
const FIELD = 'flex min-w-0 flex-col gap-1.5';
export const FX_QR_BODY_TARGET = 'quick-reply-body';

/** "Create /greeting quick reply" / "Save quick reply". */
export function fxQuickReplyLabel(editing: boolean, shortcut: string): string {
  const verb = editing ? 'Save' : 'Create';
  const s = shortcut.trim();
  return s ? `${verb} ${s} quick reply` : `${verb} quick reply`;
}

export function FxQuickReplyDialog({
  item,
  onClose,
  onCreate,
  onUpdate,
}: QuickReplyDialogProps) {
  const editing = item !== null;
  const [shortcut, setShortcut] = useState(item?.shortcut ?? '');
  const [body, setBody] = useState(item?.body ?? '');
  const [saving, setSaving] = useState(false);
  const why = useFxActionError();
  useHideMainAction(true);

  const valid = body.trim().length > 0;

  const handleSave = async () => {
    if (!valid || saving) return;
    setSaving(true);
    why.clear();
    const trimmedShortcut = shortcut.trim();
    try {
      if (editing) {
        await onUpdate(item.id, {
          shortcut: trimmedShortcut || null,
          body: body.trim(),
        });
      } else {
        await onCreate({
          shortcut: trimmedShortcut || null,
          body: body.trim(),
        });
      }
      onClose();
    } catch (e) {
      why.show(
        e instanceof Error ? e.message : "Couldn't save the quick reply.",
      );
      setSaving(false);
    }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent
        data-fx-quick-reply-dialog=""
        showCloseButton={false}
        className="max-w-lg gap-4 rounded-(--fx-r-l) border-(--fx-line) bg-(--fx-surface) p-6 text-(--fx-ink) max-sm:w-[calc(100%-32px)] max-sm:p-4"
      >
        <div className="flex flex-col gap-1">
          <DialogTitle className="text-lg font-bold text-(--fx-ink)">
            {editing ? 'Edit quick reply' : 'New quick reply'}
          </DialogTitle>
          <DialogDescription className="text-sm text-(--fx-ink-2)">
            A canned response agents insert from the composer.
          </DialogDescription>
        </div>
        <div className={FIELD}>
          <label htmlFor="fx-qr-shortcut" className={LABEL}>
            Shortcut
          </label>
          <Input
            id="fx-qr-shortcut"
            value={shortcut}
            placeholder="/greeting"
            onChange={(e) => setShortcut(e.target.value)}
            autoFocus
          />
        </div>
        <div className={FIELD} data-fx-pulse-target={FX_QR_BODY_TARGET}>
          <label htmlFor="fx-qr-body" className={LABEL}>
            Message
          </label>
          <Textarea
            id="fx-qr-body"
            value={body}
            rows={4}
            onChange={(e) => setBody(e.target.value)}
          />
        </div>
        <div className="mt-1 flex flex-nowrap items-start justify-end gap-2 max-sm:pb-6">
          <Button
            type="button"
            variant="fx-quiet"
            className="h-auto min-h-11 rounded-(--fx-r-pill) px-5"
            onClick={onClose}
            disabled={saving}
          >
            Cancel
          </Button>
          <div className="relative">
            <FxMainAction
              label={editing ? 'Save quick reply' : 'Create quick reply'}
              fullLabel={fxQuickReplyLabel(editing, shortcut)}
              working={saving}
              blocked={
                valid
                  ? undefined
                  : {
                      reason: 'Enter the message.',
                      pulseTarget: FX_QR_BODY_TARGET,
                    }
              }
              onClick={() => void handleSave()}
            />
            <FxActionError message={why.message} />
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
