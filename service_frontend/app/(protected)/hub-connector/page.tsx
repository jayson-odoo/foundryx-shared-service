'use client';

import { useCallback, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Settings } from 'lucide-react';
import { toast } from '@/lib/toast';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { PageHeader } from '@/components/platform/page-header';
import { ResourceList } from '@/components/platform/resource-list';
import { useCan } from '@/hooks/use-can';
import { hubConnectorErrorMessage, useSyncNow } from '@/hooks/use-hub-connector';
import { CreateHubDialog } from './components/create-hub-dialog';
import { HUB_MANAGE, HUB_VIEW } from './components/hub-meta';
import { useHubsListConfig } from './components/use-hubs-list-config';

/** Hub Connector > Hubs: the partner platforms that see our availability. */
export default function HubConnectorPage() {
  const { can } = useCan();
  const [creating, setCreating] = useState(false);
  const [nonce, setNonce] = useState(0);
  const onCreate = useCallback(() => setCreating(true), []);
  const config = useHubsListConfig(onCreate, nonce);
  const router = useRouter();
  const { syncing, sync } = useSyncNow();

  const syncNow = useCallback(async () => {
    try {
      const res = await sync();
      if (res.lastError) toast.error(res.lastError);
      else toast.success(`${res.products} product${res.products === 1 ? '' : 's'} synced`);
      setNonce((n) => n + 1);
    } catch (err) {
      toast.error(hubConnectorErrorMessage(err, 'Could not sync. Please try again.'));
    }
  }, [sync]);

  return (
    <RequirePermission permission={HUB_VIEW}>
      <Container width="fluid">
        <PageHeader
          actions={
            can(HUB_MANAGE) ? (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" mode="icon" aria-label="Settings">
                    <Settings className="size-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem disabled={syncing} onSelect={() => void syncNow()}>
                    Sync now
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => router.push('/settings/integrations')}>
                    CRM stock feed
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            ) : undefined
          }
        />
        <ResourceList config={config} hideHeader restoreFromCtx />
      </Container>
      <CreateHubDialog open={creating} onOpenChange={setCreating} onCreated={() => setNonce((n) => n + 1)} />
    </RequirePermission>
  );
}
