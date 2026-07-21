import type { StatusRegistry } from '@/components/platform/status-badge';
import type { IntegrationLogSource, IntegrationLogStatus } from '@/types/integration-logs';

/** Source badge registry — every log source reads the same everywhere. */
export const LOG_SOURCE_REGISTRY: StatusRegistry<IntegrationLogSource> = {
  inbound_api: { label: 'Inbound API', tone: 'info' },
  embed_session: { label: 'Embed', tone: 'primary' },
  outbound_meta: { label: 'Outbound', tone: 'secondary' },
  webhook_delivery: { label: 'Webhook', tone: 'warning' },
  autocount: { label: 'AutoCount', tone: 'success' },
};

/** Outcome badge registry. */
export const LOG_STATUS_REGISTRY: StatusRegistry<IntegrationLogStatus> = {
  success: { label: 'Success', tone: 'success' },
  error: { label: 'Error', tone: 'destructive' },
  pending: { label: 'Pending', tone: 'warning' },
};

export const DEVELOPER_LOGS_PATH = '/developers/logs';

export function integrationLogDetailPath(id: string): string {
  return `${DEVELOPER_LOGS_PATH}/${id}`;
}
