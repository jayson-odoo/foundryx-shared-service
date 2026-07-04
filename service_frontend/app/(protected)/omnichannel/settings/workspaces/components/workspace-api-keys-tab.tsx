'use client';

import { useCallback, useState } from 'react';
import { Info } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { ResourceList } from '@/components/platform/resource-list';
import { useApiKeyList } from './use-api-key-list';
import { MintApiKeyDialog } from './mint-api-key-dialog';

/**
 * API Keys tab — embedded ResourceList of the workspace's public-gateway keys
 * (Mint = create action → reveal dialog, Revoke = row action). Reuses the same
 * embedded-ResourceList pattern as the channel Templates tab.
 */
export function ApiKeysTab({
  workspaceId,
  creating,
}: {
  workspaceId: string | null;
  creating: boolean;
}) {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  const onMint = useCallback(() => setDialogOpen(true), []);
  const onMinted = useCallback(() => setReloadKey((k) => k + 1), []);

  const { config } = useApiKeyList(workspaceId ?? '', onMint);

  if (creating || !workspaceId) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center gap-2 py-16 text-center">
          <Info className="size-8 text-muted-foreground" />
          <p className="text-sm font-medium">API keys unavailable</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <ResourceList key={reloadKey} config={config} />
      <MintApiKeyDialog
        workspaceId={workspaceId}
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        onMinted={onMinted}
      />
    </div>
  );
}
