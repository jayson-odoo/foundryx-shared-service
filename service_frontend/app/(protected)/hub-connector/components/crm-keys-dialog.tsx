'use client';

import { useCallback, useState } from 'react';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { ResourceList } from '@/components/platform/resource-list';
import { CreateKeyDialog } from './create-key-dialog';
import { useKeysListConfig } from './use-keys-list-config';

export interface CrmKeysDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** The company's CRM keys: list, create (shown once) and revoke. */
export function CrmKeysDialog({ open, onOpenChange }: CrmKeysDialogProps) {
  const [creating, setCreating] = useState(false);
  const [nonce, setNonce] = useState(0);
  const onCreate = useCallback(() => setCreating(true), []);
  const config = useKeysListConfig(onCreate, nonce);

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="max-w-3xl" aria-describedby={undefined}>
          <DialogHeader>
            <DialogTitle>CRM keys</DialogTitle>
          </DialogHeader>
          <DialogBody>
            {open && <ResourceList config={config} hideHeader />}
          </DialogBody>
        </DialogContent>
      </Dialog>
      <CreateKeyDialog open={creating} onOpenChange={setCreating} onCreated={() => setNonce((n) => n + 1)} />
    </>
  );
}
