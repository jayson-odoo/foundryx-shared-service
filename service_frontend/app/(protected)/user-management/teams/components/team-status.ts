import type { StatusRegistry } from '@/components/platform/status-badge';

export type TeamStatus = 'active' | 'inactive';

/** Uniform status pill mapping for teams (derived from `isActive`, not a
 * stored status - teams have no soft-trash/lifecycle graph, D-A8-19). */
export const TEAM_STATUS_REGISTRY: StatusRegistry<TeamStatus> = {
  active: { label: 'Active', tone: 'success' },
  inactive: { label: 'Inactive', tone: 'secondary' },
};

export function teamStatus(isActive: boolean): TeamStatus {
  return isActive ? 'active' : 'inactive';
}
