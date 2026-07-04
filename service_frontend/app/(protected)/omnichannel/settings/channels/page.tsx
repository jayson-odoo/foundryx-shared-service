'use client';

import { Fragment, useCallback, useState } from 'react';
import {
  Toolbar,
  ToolbarDescription,
  ToolbarHeading,
  ToolbarPageTitle,
} from '@/partials/common/toolbar';
import { Container } from '@/components/common/container';
import { ResourceList } from '@/components/platform/resource-list';
import { RequirePermission } from '@/components/common/require-permission';
import { ChannelConnectWizard } from '@/components/platform/channel-connect-wizard';
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
          <Toolbar>
            <ToolbarHeading>
              <ToolbarPageTitle />
              <ToolbarDescription>
                Connect and manage your WhatsApp Business numbers.
              </ToolbarDescription>
            </ToolbarHeading>
          </Toolbar>
        </Container>
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
