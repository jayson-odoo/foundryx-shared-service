import type { StatusRegistry } from '@/components/platform/status-badge';
import type { WorkspaceStatus } from '@/types/omnichannel';

/** Uniform status pill mapping for workspaces (plan 04 - statuses table, WORKSPACE scope). */
export const WORKSPACE_STATUS_REGISTRY: StatusRegistry<WorkspaceStatus> = {
  ACTIVE: { label: 'Active', tone: 'success' },
  INACTIVE: { label: 'Inactive', tone: 'secondary' },
};

/** Statuses an admin may set on the workspace form. */
export const WORKSPACE_STATUSES: WorkspaceStatus[] = ['ACTIVE', 'INACTIVE'];
