'use client';

/** Moves one workspace to another of the tenant's client apps. Its keys and
 * webhooks key off workspace_id and keep working; an in-flight partner connect
 * session of the old client app stops working. */
import { useEffect, useState } from 'react';
import type { ClientApp, ClientAppWorkspace } from '@/types/omnichannel';
import { toast } from '@/lib/toast';
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
import { SearchSelect } from '@/components/platform/search-select';

export interface MoveWorkspaceDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workspace: ClientAppWorkspace | null;
  /** The client app the workspace currently belongs to (excluded as a target). */
  fromClientAppId: string | null;
  apps: ClientApp[];
  onMove: (targetClientAppId: string, workspaceId: string) => Promise<unknown>;
}

export function MoveWorkspaceDialog({
  open,
  onOpenChange,
  workspace,
  fromClientAppId,
  apps,
  onMove,
}: MoveWorkspaceDialogProps) {
  const [targetId, setTargetId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (open) setTargetId(null);
  }, [open]);

  const options = apps
    .filter((a) => a.id !== fromClientAppId)
    .map((a) => ({ label: a.name, value: a.id }));

  const submit = async () => {
    if (!workspace || !targetId) return;
    setSubmitting(true);
    try {
      await onMove(targetId, workspace.id);
      toast.success(`${workspace.name} moved.`);
      onOpenChange(false);
    } catch (error) {
      toast.error(
        error instanceof Error
          ? error.message
          : 'Could not move the workspace.',
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !submitting && onOpenChange(v)}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>Move workspace</DialogTitle>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-4">
          <p className="text-sm text-muted-foreground">
            Move{' '}
            <span className="font-medium text-foreground">
              {workspace?.name}
            </span>{' '}
            to another client app.
          </p>
          <div className="flex flex-col gap-1.5">
            <Label>Target client app</Label>
            {options.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Create another client app first.
              </p>
            ) : (
              <SearchSelect
                options={options}
                value={targetId}
                onChange={setTargetId}
                placeholder="Choose a client app"
                ariaLabel="Target client app"
              />
            )}
          </div>
        </DialogBody>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={submitting}
          >
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            disabled={submitting || !targetId}
            data-testid="move-workspace-submit"
          >
            Move
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
