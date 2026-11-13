'use client';

import { useCallback, useState } from 'react';
import { Info } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { ResourceList } from '@/components/platform/resource-list';
import type { ApiKeyItem } from '@/types/api-keys';
import { useApiKeyList, type RevokePark } from './use-api-key-list';
import { RevokeApiKeyDialog } from './revoke-api-key-dialog';
import { MintApiKeyDialog } from './mint-api-key-dialog';

/**
 * API Keys tab - embedded ResourceList of the workspace's public-gateway keys
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

  const [revoking, setRevoking] = useState<{ key: ApiKeyItem; park: RevokePark } | null>(null);
  const onRevokeWithEndpoints = useCallback(
    (key: ApiKeyItem, park: RevokePark) => setRevoking({ key, park }),
    [],
  );

  const { config } = useApiKeyList(workspaceId ?? '', onMint, onRevokeWithEndpoints);

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
      <ResourceList key={reloadKey} config={config} hideHeader />
      <RevokeApiKeyDialog
        keyName={revoking?.key.name ?? null}
        endpointCount={revoking?.key.webhookEndpointCount ?? 0}
        onCancel={() => setRevoking(null)}
        onConfirm={(pauseEndpoints) => {
          const park = revoking?.park;
          setRevoking(null);
          void park?.({ pauseEndpoints });
        }}
      />
      <MintApiKeyDialog
        workspaceId={workspaceId}
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        onMinted={onMinted}
      />
    </div>
  );
}
