'use client';

import { WebhooksPanel } from '../../channels/components/channel-webhooks-tab';
import { whatsappWebhookService } from '@/services/whatsapp-webhook-service';

const loadWorkspaceList = (workspaceId: string) =>
  whatsappWebhookService.listForWorkspace(workspaceId);

/**
 * Workspace Webhooks tab - the workspace's all-channels endpoints, listed even
 * when no channel is connected. Same row actions as the channel tab, no Add.
 */
export function WorkspaceWebhooksTab({ workspaceId }: { workspaceId: string | null }) {
  if (!workspaceId) return null;
  return <WebhooksPanel scopeId={workspaceId} channelId={null} loadList={loadWorkspaceList} />;
}
