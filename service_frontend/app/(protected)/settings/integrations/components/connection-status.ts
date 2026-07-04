import type { StatusRegistry } from '@/components/platform/status-badge';
import type { ConnectionStatus } from '@/types/integration';

/**
 * Status pill mapping for connections (plan 06 D6). UNVERIFIED shouts until
 * the first successful test — the wizard's "test before done" ceremony,
 * carried by the list/form instead.
 */
export const CONNECTION_STATUS_REGISTRY: StatusRegistry<ConnectionStatus> = {
  ACTIVE: { label: 'Connected', tone: 'success' },
  UNVERIFIED: { label: 'Unverified', tone: 'warning' },
  ERROR: { label: 'Error', tone: 'destructive' },
};
