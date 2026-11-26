'use client';

import { useCallback, useState } from 'react';
import { Settings } from 'lucide-react';
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
import { CreateHubDialog } from './components/create-hub-dialog';
import { CrmKeysDialog } from './components/crm-keys-dialog';
import { HUB_KEYS_MANAGE, HUB_VIEW } from './components/hub-meta';
import { useHubsListConfig } from './components/use-hubs-list-config';

/** Hub Connector > Hubs: the partner platforms that see our availability. */
export default function HubConnectorPage() {
  const { can } = useCan();
  const [creating, setCreating] = useState(false);
  const [keysOpen, setKeysOpen] = useState(false);
  const [nonce, setNonce] = useState(0);
  const onCreate = useCallback(() => setCreating(true), []);
  const config = useHubsListConfig(onCreate, nonce);

  return (
    <RequirePermission permission={HUB_VIEW}>
      <Container width="fluid">
        <PageHeader
          actions={
            can(HUB_KEYS_MANAGE) ? (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" mode="icon" aria-label="Settings">
                    <Settings className="size-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onSelect={() => setKeysOpen(true)}>CRM keys</DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            ) : undefined
          }
        />
        <ResourceList config={config} hideHeader restoreFromCtx />
      </Container>
      <CreateHubDialog open={creating} onOpenChange={setCreating} onCreated={() => setNonce((n) => n + 1)} />
      <CrmKeysDialog open={keysOpen} onOpenChange={setKeysOpen} />
    </RequirePermission>
  );
}
