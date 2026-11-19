'use client';

/**
 * Save or rename a saved inbox view with the Foundryx UIUX switch on (slice
 * W1-INBOX). Same form and the same requests as the legacy dialog (shared
 * `useInboxViewForm`); the playbook dialog words and buttons: the safe button
 * is named for what it keeps, the action is verb + object and is the
 * dialog's one red action, so the page's red action hides while it is open.
 */
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
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { useHideMainAction } from '@/components/fx/actions/page-actions-context';
import type { InboxViewDialogProps } from '../inbox-view-dialog';
import { useInboxViewForm } from '../use-inbox-view-form';

export function FxInboxViewDialog({
  open,
  onOpenChange,
  view,
  canShare,
  onCreate,
  onUpdate,
}: InboxViewDialogProps) {
  const { editing, submitting, form, submit } = useInboxViewForm({
    open,
    onOpenChange,
    view,
    onCreate,
    onUpdate,
  });
  useHideMainAction(open);

  const name = form.watch('name');
  const typed = name.trim();
  const action = editing ? 'Rename view' : 'Save view';
  const fullAction = typed
    ? editing
      ? `Rename view to ${typed}`
      : `Save view as ${typed}`
    : action;

  return (
    <Dialog open={open} onOpenChange={(v) => !submitting && onOpenChange(v)}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>
            {editing
              ? `Rename ${view?.name ?? 'this view'}?`
              : 'Save these filters as a view?'}
          </DialogTitle>
          <DialogDescription>
            {editing
              ? 'Its filters stay as they are.'
              : 'It keeps the filters you have chosen now.'}
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="view-name">Name</Label>
            <Input
              id="view-name"
              autoFocus
              value={name}
              onChange={(e) =>
                form.setValue('name', e.target.value, { shouldValidate: true })
              }
              data-testid="inbox-view-name"
            />
            {form.formState.errors.name && (
              <p className="text-xs text-(--fx-act)">
                {form.formState.errors.name.message}
              </p>
            )}
          </div>
          {canShare && (
            <label className="flex cursor-pointer items-center justify-between gap-3 rounded-(--fx-r-m) border border-(--fx-line) p-3 text-sm text-(--fx-ink)">
              Shared with the workspace
              <Switch
                checked={form.watch('isShared')}
                onCheckedChange={(v) => form.setValue('isShared', v)}
                aria-label="Shared with the workspace"
                data-testid="inbox-view-shared"
              />
            </label>
          )}
        </DialogBody>
        <DialogFooter className="items-center gap-2">
          <Button
            variant="fx-quiet"
            className="min-h-11 px-4"
            onClick={() => onOpenChange(false)}
            disabled={submitting}
          >
            {editing ? 'Keep the name' : 'Not now'}
          </Button>
          <Button
            variant="fx-main"
            className="min-h-11 px-5"
            onClick={submit}
            disabled={submitting || !typed}
            aria-label={fullAction}
            data-testid="inbox-view-submit"
          >
            {action}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
