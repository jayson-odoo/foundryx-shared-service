'use client';

/**
 * Save/rename saved-view dialog (plan 27, AC-IVE-18/22). Create captures the
 * CURRENT filter snapshot; edit only touches name/shared (the filter itself
 * isn't re-editable here - re-save-as-new covers that). The Shared switch is
 * HIDDEN (not just disabled) for a caller without `inbox_views.manage`
 * (D-A3-11) - foolproof-UI, never offer a control that will 403.
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
import { useFx } from '@/hooks/use-fx';
import type { InboxView } from '@/types/omnichannel';
import { FxInboxViewDialog } from './fx/fx-inbox-view-dialog';
import type { InboxViewFormValues } from './inbox-view-schema';
import { useInboxViewForm } from './use-inbox-view-form';

export interface InboxViewDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** null = create (a new saved view over the current filters). */
  view: InboxView | null;
  /** Hides the Shared switch entirely when false (foolproof-UI, D-A3-11). */
  canShare: boolean;
  onCreate: (values: InboxViewFormValues) => Promise<unknown>;
  onUpdate: (id: string, values: InboxViewFormValues) => Promise<unknown>;
}

export function InboxViewDialog(props: InboxViewDialogProps) {
  // Foundryx UIUX switch (playbook-uiux.md): the playbook dialog. Off renders
  // the legacy body below, unchanged.
  return useFx() ? <FxInboxViewDialog {...props} /> : <InboxViewDialogLegacy {...props} />;
}

function InboxViewDialogLegacy({ open, onOpenChange, view, canShare, onCreate, onUpdate }: InboxViewDialogProps) {
  const { editing, submitting, form, submit } = useInboxViewForm({ open, onOpenChange, view, onCreate, onUpdate });

  return (
    <Dialog open={open} onOpenChange={(v) => !submitting && onOpenChange(v)}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>{editing ? 'Rename view' : 'Save view'}</DialogTitle>
          <DialogDescription>
            {editing ? 'A saved view\'s name and sharing.' : 'A saved snapshot of the current filters.'}
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="view-name">Name</Label>
            <Input
              id="view-name"
              autoFocus
              value={form.watch('name')}
              onChange={(e) => form.setValue('name', e.target.value, { shouldValidate: true })}
              data-testid="inbox-view-name"
            />
            {form.formState.errors.name && (
              <p className="text-xs text-destructive">{form.formState.errors.name.message}</p>
            )}
          </div>
          {canShare && (
            <div className="flex items-center justify-between gap-3 rounded-md border p-3">
              <Label htmlFor="view-shared" className="cursor-pointer">
                Shared with the workspace
              </Label>
              <Switch
                id="view-shared"
                checked={form.watch('isShared')}
                onCheckedChange={(v) => form.setValue('isShared', v)}
                data-testid="inbox-view-shared"
              />
            </div>
          )}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            disabled={submitting || !form.watch('name').trim()}
            data-testid="inbox-view-submit"
          >
            {editing ? 'Save changes' : 'Save view'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
