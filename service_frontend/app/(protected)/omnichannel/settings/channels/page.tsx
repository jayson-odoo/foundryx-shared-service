'use client';

import { Fragment, useCallback, useState } from 'react';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { ChannelConnectWizard } from '@/components/platform/channel-connect-wizard';
import { ResourceList } from '@/components/platform/resource-list';
import { useChannelsListConfig } from './components/use-channels-list-config';

export default function ChannelsPage() {
  const [wizardOpen, setWizardOpen] = useState(false);
  // Bumped after a successful connect to remount the list (re-fetch).
  const [reloadKey, setReloadKey] = useState(0);

  const onConnect = useCallback(() => setWizardOpen(true), []);
  const config = useChannelsListConfig({ onConnect });

  return (
    <RequirePermission permission="channels.read">
      <Fragment>
        <Container width="fluid">
          <ResourceList key={reloadKey} config={config} />
        </Container>

        <ChannelConnectWizard
          open={wizardOpen}
          onOpenChange={setWizardOpen}
          onConnected={() => setReloadKey((k) => k + 1)}
        />
      </Fragment>
    </RequirePermission>
  );
}
