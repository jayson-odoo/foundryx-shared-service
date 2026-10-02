'use client';

/**
 * Lifecycle tab (plan 25 D1/AC-CDM-30) - the workspace's OWN contact-lifecycle
 * pipeline on the existing status canvas, scoped to `scopeId = workspaceId`.
 * Clones `forms/components/form-flow-tab.tsx` exactly: statuses here are
 * tenant-owned from birth (materialized at workspace creation), so canvas
 * edits apply directly - no platform-fork gymnastics. The status entity
 * `omnichannel_contact_lifecycle` is registered on the backend in S2 - until
 * then this renders the canvas's own graceful empty state (no graph yet).
 */
import { EntityFlow, type LayoutController } from '@/components/platform/status-engine';
import { useStatusGraph } from '@/hooks/use-status-engine';

export const CONTACT_LIFECYCLE_ENTITY = 'omnichannel_contact_lifecycle';

export interface WorkspaceLifecycleTabProps {
  workspaceId: string;
  workspaceName: string;
  editing: boolean;
  onDirtyChange?: (dirty: boolean) => void;
  layoutController?: React.MutableRefObject<LayoutController | null>;
}

export function WorkspaceLifecycleTab({
  workspaceId,
  workspaceName,
  editing,
  onDirtyChange,
  layoutController,
}: WorkspaceLifecycleTabProps) {
  const engine = useStatusGraph(CONTACT_LIFECYCLE_ENTITY, workspaceId);

  return (
    <EntityFlow
      entityType={CONTACT_LIFECYCLE_ENTITY}
      entityLabel={`${workspaceName} contact lifecycle`}
      engine={engine}
      editing={editing}
      onDirtyChange={onDirtyChange}
      layoutController={layoutController}
    />
  );
}
