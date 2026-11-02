'use client';

import { Fragment, useCallback, useState } from 'react';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { ChannelConnectWizard } from '@/components/platform/channel-connect-wizard';
import { ResourceList } from '@/components/platform/resource-list';
import { ReplaceTokenDialog } from './components/replace-token-dialog';
import type { Channel } from '@/types/omnichannel';
import { useChannelsListConfig } from './components/use-channels-list-config';

export default function ChannelsPage() {
  const [wizardOpen, setWizardOpen] = useState(false);
  // Bumped after a successful connect to remount the list (re-fetch).
  const [reloadKey, setReloadKey] = useState(0);

  // The channel whose token is being replaced; non-null opens the dialog.
  const [replacing, setReplacing] = useState<Channel | null>(null);

  const onConnect = useCallback(() => setWizardOpen(true), []);
  const config = useChannelsListConfig({ onConnect, onReplaceToken: setReplacing });

  return (
    <RequirePermission permission="channels.read">
      <Fragment>
        <Container width="fluid">
          <ResourceList key={reloadKey} config={config} />
        </Container>

        {replacing && (
          <ReplaceTokenDialog
            channel={replacing}
            open
            onOpenChange={(open) => !open && setReplacing(null)}
            onReplaced={() => setReloadKey((k) => k + 1)}
          />
        )}

        <ChannelConnectWizard
          open={wizardOpen}
          onOpenChange={setWizardOpen}
          onConnected={() => setReloadKey((k) => k + 1)}
        />
      </Fragment>
    </RequirePermission>
  );
}
