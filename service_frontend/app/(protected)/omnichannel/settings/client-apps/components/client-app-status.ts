import type { ClientAppStatus } from '@/types/omnichannel';
import type { StatusRegistry } from '@/components/platform/status-badge';

export const CLIENT_APP_STATUS_REGISTRY: StatusRegistry<ClientAppStatus> = {
  ACTIVE: { label: 'Active', tone: 'success' },
  DISABLED: { label: 'Disabled', tone: 'destructive' },
};
