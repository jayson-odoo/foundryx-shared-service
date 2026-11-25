'use client';

/** Read-only workspace list of one client app, each row offering a Move. */
import { FolderInput } from 'lucide-react';
import type { ClientApp, ClientAppWorkspace } from '@/types/omnichannel';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { ClampedText } from '@/components/platform/clamped-text';

export interface ClientAppWorkspacesDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  app: ClientApp | null;
  onMove: (workspace: ClientAppWorkspace) => void;
}

export function ClientAppWorkspacesDialog({
  open,
  onOpenChange,
  app,
  onMove,
}: ClientAppWorkspacesDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>
            {app ? `${app.name} - workspaces` : 'Workspaces'}
          </DialogTitle>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-2">
          {app && app.workspaces.length === 0 && (
            <p className="text-sm text-muted-foreground">
              This client app has no workspaces yet.
            </p>
          )}
          {app?.workspaces.map((ws) => (
            <div
              key={ws.id}
              className="flex items-center justify-between gap-3 rounded-md border p-3"
            >
              <div className="flex min-w-0 items-center gap-2">
                <ClampedText text={ws.name} lines={1} className="font-medium" />
                {ws.isDefault && (
                  <Badge variant="secondary" appearance="light" size="sm">
                    Default
                  </Badge>
                )}
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => onMove(ws)}
                data-testid={`move-workspace-${ws.id}`}
              >
                <FolderInput className="size-4" />
                Move
              </Button>
            </div>
          ))}
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}
