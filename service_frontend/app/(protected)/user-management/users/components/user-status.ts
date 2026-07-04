import type { StatusRegistry } from '@/components/platform/status-badge';
import type { UserStatus } from '@/types/user';

/** Uniform status pill mapping for users (plan 02 §4 status pill). */
export const USER_STATUS_REGISTRY: StatusRegistry<UserStatus> = {
  ACTIVE: { label: 'Active', tone: 'success' },
  INACTIVE: { label: 'Inactive', tone: 'secondary' },
  BLOCKED: { label: 'Blocked', tone: 'destructive' },
  INVITED: { label: 'Invited', tone: 'warning' },
};

/** Statuses an admin may set in the Profile form (INVITED is system-managed). */
export const ASSIGNABLE_STATUSES: Exclude<UserStatus, 'INVITED'>[] = [
  'ACTIVE',
  'INACTIVE',
  'BLOCKED',
];
