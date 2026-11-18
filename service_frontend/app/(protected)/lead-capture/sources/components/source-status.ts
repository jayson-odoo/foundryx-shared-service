import type { StatusRegistry } from '@/components/platform/status-badge';
import type { LeadSourceStatus } from '@/types/lead-capture-wizard';
import type { DeliveryStatus } from '@/types/lead-capture-sources';

/** Source status pill (plan 64 section 4). */
export const SOURCE_STATUS_REGISTRY: StatusRegistry<LeadSourceStatus> = {
  DRAFT: { label: 'Draft', tone: 'secondary' },
  WAITING_FOR_TEST: { label: 'Waiting for test', tone: 'warning' },
  LIVE: { label: 'Live', tone: 'success' },
  NEEDS_RECONNECT: { label: 'Reconnect', tone: 'destructive' },
  DISCONNECTED: { label: 'Disconnected', tone: 'secondary' },
};

export const DELIVERY_STATUS_REGISTRY: StatusRegistry<DeliveryStatus> = {
  PENDING: { label: 'Sending', tone: 'warning' },
  SUCCESS: { label: 'Delivered', tone: 'success' },
  FAILED: { label: 'Failed', tone: 'destructive' },
};

export const PLATFORM_LABELS: Record<string, string> = { facebook: 'Facebook' };
