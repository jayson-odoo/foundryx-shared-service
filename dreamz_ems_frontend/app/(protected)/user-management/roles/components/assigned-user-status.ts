import type { StatusRegistry } from '@/components/platform/status-badge';
import type { UserStatus } from '@/types/user';

/** Status pill mapping for assigned users (mirrors the Users registry). */
export const ASSIGNED_USER_STATUS_REGISTRY: StatusRegistry<UserStatus> = {
  ACTIVE: { label: 'Active', tone: 'success' },
  INACTIVE: { label: 'Inactive', tone: 'secondary' },
  BLOCKED: { label: 'Blocked', tone: 'destructive' },
  INVITED: { label: 'Invited', tone: 'warning' },
};
