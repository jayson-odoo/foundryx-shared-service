'use client';

/**
 * The channels page with the Foundryx UIUX switch on (gap audit 12,
 * "Connected services"): a card per service with its own Connect, then the
 * connected channels as cards (the list's search, filters, Active/Trashed,
 * export and actions unchanged). The connect wizard, the Replace token
 * dialog and every request are the legacy page's.
 */
import { useCallback, useState } from 'react';
import { Container } from '@/components/common/container';
import { PageHeader } from '@/components/platform/page-header';
import { ResourceList } from '@/components/platform/resource-list';
import { ChannelConnectWizard } from '@/components/platform/channel-connect-wizard';
import { useCan } from '@/hooks/use-can';
import type { Channel, ChannelType } from '@/types/omnichannel';
import { ReplaceTokenDialog } from './replace-token-dialog';
import { useChannelsListConfig } from './use-channels-list-config';
import { useChannelTypeCounts } from './use-channel-type-counts';
import { FxConnectServices } from './fx-connect-services';

export function FxChannelsPage() {
  const { can } = useCan();
  const [wizardType, setWizardType] = useState<ChannelType | null>(null);
  // Bumped after a successful connect or token replace to remount the list.
  const [reloadKey, setReloadKey] = useState(0);
  // Bumped after anything that changes how many channels there are.
  const [countsKey, setCountsKey] = useState(0);
  const [replacing, setReplacing] = useState<Channel | null>(null);
  const counts = useChannelTypeCounts(countsKey);

  const onConnect = useCallback(() => setWizardType('WHATSAPP'), []);
  const onFxChanged = useCallback(() => setCountsKey((k) => k + 1), []);
  const config = useChannelsListConfig({ onConnect, onReplaceToken: setReplacing, onFxChanged });
  const reload = () => {
    setReloadKey((k) => k + 1);
    setCountsKey((k) => k + 1);
  };

  return (
    <Container width="fluid">
      <div className="flex flex-col gap-4">
        <PageHeader />
        <FxConnectServices counts={counts} canConnect={can('channels.manage')} onConnect={setWizardType} />
        <ResourceList key={reloadKey} config={config} hideHeader restoreFromCtx />
      </div>

      {replacing && (
        <ReplaceTokenDialog
          channel={replacing}
          open
          onOpenChange={(open) => !open && setReplacing(null)}
          onReplaced={reload}
        />
      )}

      <ChannelConnectWizard
        open={wizardType !== null}
        initialType={wizardType ?? undefined}
        onOpenChange={(open) => !open && setWizardType(null)}
        onConnected={reload}
      />
    </Container>
  );
}
