import type { StatusRegistry } from '@/components/platform/status-badge';
import type { ConnectorGrantStatus } from '@/types/connector';

export const CONNECTOR_STATUS_REGISTRY: StatusRegistry<ConnectorGrantStatus> = {
  active: { label: 'Active', tone: 'success' },
  revoked: { label: 'Revoked', tone: 'destructive' },
  expired: { label: 'Expired', tone: 'secondary' },
};

export const CONNECTOR_PATH = '/settings/claude-connector';

export function connectorGrantPath(id: string): string {
  return `${CONNECTOR_PATH}/${encodeURIComponent(id)}`;
}
