'use client';

import { useCallback, useState } from 'react';
import { toast } from 'sonner';
import { ResourceList } from '@/components/platform/resource-list';
import type { WebhookEndpoint } from '@/types/whatsapp-webhook';
import { useWebhookList } from './use-webhook-list';
import { useWebhooks } from './use-webhooks';
import { WebhookEndpointDialog } from './webhook-endpoint-dialog';
import { WebhookSecretDialog } from './webhook-secret-dialog';
import { WebhookDeliveriesDialog } from './webhook-deliveries-dialog';

/**
 * Webhooks tab - embedded ResourceList of the channel's consumer-webhook
 * endpoints. Add/Edit ride a shared dialog (create reveals the signing secret
 * ONCE); Rotate reveals a fresh secret; View deliveries opens the read-only log.
 * Enable / disable / delete run inline from the row action menu.
 */
export function ChannelWebhooksTab({ channelId }: { channelId: string }) {
  const { rotate } = useWebhooks(channelId);
  const [reloadKey, setReloadKey] = useState(0);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<WebhookEndpoint | null>(null);
  const [rotatedSecret, setRotatedSecret] = useState<string | null>(null);
  const [deliveriesOf, setDeliveriesOf] = useState<WebhookEndpoint | null>(null);

  const reload = useCallback(() => setReloadKey((k) => k + 1), []);

  const onCreate = useCallback(() => {
    setEditing(null);
    setDialogOpen(true);
  }, []);

  const onEdit = useCallback((endpoint: WebhookEndpoint) => {
    setEditing(endpoint);
    setDialogOpen(true);
  }, []);

  const onRotate = useCallback(
    async (endpoint: WebhookEndpoint) => {
      try {
        const result = await rotate(endpoint.id);
        setRotatedSecret(result.signingSecret);
      } catch {
        toast.error('Could not rotate the secret. Please retry.');
      }
    },
    [rotate],
  );

  const onViewDeliveries = useCallback((endpoint: WebhookEndpoint) => {
    setDeliveriesOf(endpoint);
  }, []);

  const { config } = useWebhookList(channelId, {
    onCreate,
    onEdit,
    onRotate,
    onViewDeliveries,
  });

  return (
    <div className="flex flex-col gap-3">
      <ResourceList key={reloadKey} config={config} hideHeader />

      <WebhookEndpointDialog
        channelId={channelId}
        endpoint={editing}
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        onSaved={reload}
      />

      <WebhookSecretDialog
        secret={rotatedSecret}
        onOpenChange={(open) => !open && setRotatedSecret(null)}
      />

      <WebhookDeliveriesDialog
        endpoint={deliveriesOf}
        onOpenChange={(open) => !open && setDeliveriesOf(null)}
      />
    </div>
  );
}
